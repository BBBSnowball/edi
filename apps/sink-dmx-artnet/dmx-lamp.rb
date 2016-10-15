#!/usr/bin/env ruby
# encoding: UTF-8

#TODO Farbprogramme
#TODO testen, ob enabled/disabled state auch regelmäßig aufs dmx geschrieben werden muss

#key dmx.lamp.subraum.control, body ~= (on|off)
#key dmx.lamp.subraum.0, body ~= (\d,\d,\d|html-farbe|programmname)

#Lampenids: 8, 24, 96

#config
def config
  $subsystem = "subraum"
  $program_path = './programs/'
  $channel_write_interval = 0.01
  $debug = false
  $server = {
    0  => ["172.31.65.70", "172.31.64.110"],
    30 => ["172.31.65.74", "172.31.65.196"],
    10 => ["172.31.65.70"],
  }
  $server[31] = $server[30]
  $server[11] = $server[10]
  $server[12] = $server[10]
  $quiet_time = 10
end  #/config

def config_lamps(c)
  # id, universe, address, default program
  c.add_lamp( 2, 0,  2, "backgroundA")
  c.add_lamp( 6, 0,  6, "backgroundB")
  c.add_lamp(10, 0, 10, "backgroundB")
  c.add_lamp(14, 0, 14, "backgroundB")
  c.add_lamp(18, 0, 18, "backgroundB")
  c.add_lamp(22, 0, 22, "green")
  c.add_lamp(25, 0, 25, "green")
  c.add_lamp(30, 0, 30, "backgroundA")
  c.add_lamp(34, 0, 34, "backgroundA")
end

require "bunny"
require "socket"
require "thread"
require "json"

class Artnet
  def initialize
    @socket = UDPSocket.new
    @sema = Mutex.new
    @serversocket = UDPSocket.new
    @serversocket.bind("0.0.0.0", 6454)
    @time_of_recent_message_for_universe = {}
    $server.each_pair do |universe, servers|
      @time_of_recent_message_for_universe[universe] = Time.now - $quiet_time
    end
    @thread = Thread.new do
      forward_packets
    end
  end

  def possibly_send(universe)
    @sema.synchronize do
      return if @time_of_recent_message_for_universe[universe.id] + $quiet_time > Time.now
      return unless $server[universe.id]

      channels = universe.channel_data
      msg = "Art-Net\0\0\x50\0\0\0\0\0\0\0\x00" + channels
      msg[17] = (channels.length&0xff).chr
      msg[16] = ((channels.length>>8)&0xff).chr
      msg[14] = (universe.id&0xff).chr
      msg[15] = ((universe.id>>8)&0xff).chr
      $server[universe.id].each do |server|
        @socket.send(msg, 0, server, 6454)
      end
    end
  end

  def forward_packets
    begin
      while true
        msgaddr = @serversocket.recvfrom(2048)
        msg = msgaddr[0]
        begin
          universe = msg[14].ord | (msg[15].ord<<8)
          puts "forwarding packet for universe #{universe}"
          @sema.synchronize do
            @time_of_recent_message_for_universe[universe] = Time.now
          end
          if $server.include? universe
            $server[universe].each do |server|
              @socket.send(msg, 0, server, 6454)
            end
          end
        rescue Interrupt
          puts "Aborting forward_packets thread because of user interrupt"
          break
        rescue
          puts "Exception in forward_packets thread: #{e}"
        end
      end
    rescue Exception => e
      puts "Fatal exception in forward_packets thread: #{e}"
      raise e
    end
  end
end

class DmxLamp
  def initialize(universe, address, default_program)
    @universe = universe
    @address = address
    @default_program = ColorProgram.to_color_program(default_program)
    @program = @default_program
    raise "abc" unless @program
  end

  attr_reader :universe, :address, :program

  def program=(value)
    @program = ColorProgram.to_color_program(value)
    unless @program and @program.respond_to? :current and @program.respond_to? :next
      raise "Invalid color: #{value}"
    end
  end

  def reset_program
    @program = @default_program
  end

  def advance_program
    @program.next
  end

  def maxchannel
    @address + 3
  end

  def update_channels(channels)
    channels[@address-1] = 0
    @program.current.each_with_index do |value, index|
      channels[@address+index] = [value, 0, 255].sort[1]
    end
    channels[@address+3] = 0
  end
end

class Channels
  def initialize(count)
    @data = "\0"*count
  end

  attr_reader :data

  def length
    @data.length
  end

  def [](index)
    @data[index].ord
  end

  def []=(index, value)
    @data[index] = value.to_i.chr
  end
end

class DmxUniverse
  def initialize(universe)
    @id = universe
    @objects = []
    @maxchannel = -1
    @channels = Channels.new(0)
  end

  attr_reader :id

  def each
    @objects.each do |obj|
      yield obj
    end
  end

  def <<(obj)
    raise "Wrong universe" if obj.universe != @id
    if obj.maxchannel > @maxchannel
      @maxchannel = obj.maxchannel
    end
    @objects << obj
  end

  def channel_data
    @channels = Channels.new(@maxchannel+1) if @maxchannel != @channels.length
    @objects.each do |obj|
      obj.update_channels(@channels)
    end
    return @channels.data
  end
end

class DmxUniverses
  def initialize
    @universes = {}
  end

  def [](index)
    if @universes.include? index
      @universes[index]
    else
      u = DmxUniverse.new(index)
      @universes[index] = u
      return u
    end
  end

  def each
    @universes.each_value do |obj|
      yield obj
    end
  end

  def <<(obj)
    self[obj.universe] << obj
  end
end

class DmxControl
  def initialize
    @sema = Mutex.new
    @enabled = true
    @universes = DmxUniverses.new
    @artnet = Artnet.new
    @lamps = {}
  end

  def add_lamp(id, universe, address, default_program)
    @sema.synchronize do
      lamp = DmxLamp.new(universe, address, default_program)
      @lamps[id] = lamp
      @universes << lamp
    end
  end

  def on
    @sema.synchronize do
      @lamps.each_pair do |lampid, lamp|
        lamp.reset_program
      end
      @enabled = true
    end
  end

  def off
    @sema.synchronize do
      @enabled = false
    end
  end

  def setprogram(lampid, program_or_color)
    raise Exception("no such lamp: #{lampid}") unless @lamps.include? lampid
    @sema.synchronize do
      @lamps[lampid].program = program_or_color
    end
  end

  def loop
    while true
      sleep($channel_write_interval)
      next unless @enabled
      @sema.synchronize do
        @lamps.each_pair do |lampid, lamp|
          lamp.advance_program
        end
        @universes.each do |universe|
          @artnet.possibly_send(universe)
        end
      end
    end
  end
end

class ColorProgram
  def self.to_color_program(color)
    program = to_color_program_unsafe(color)
    unless program and program.respond_to? :current and program.respond_to? :next
      raise "Invalid color: #{color}, #{program}"
    end
    return program
  end

  def self.to_color(color)
    to_color_or_nil(color) or raise "Invalid color: #{color}"
  end

  def current
    fail "not implemented"
  end

  def next
    fail "not implemented"
  end

  private

  def self.to_color_program_unsafe(color)
    return color if color.is_a?(ColorProgram)
    col = to_color_or_nil(color)
    return ConstantColorProgram.new(col) if col
    p = File.join($program_path,color+".rb")
    if File.exist?(p) && File.realpath(p).start_with?($program_path) then
      c = load_color_subclass(p)
      return c if c
    end
    p = File.join($program_path,color)
    if File.exist?(p) && File.realpath(p).start_with?($program_path)
      return ColorProgram.from_file(p)
    end
    fail "Unbekannte Farbe: #{color}"
  end

  def self.to_color_or_nil(color)
    if color.is_a?(String)
      color.downcase!
      load_colors unless @@colors
      return @@colors[color] || parse_color(color)
    else
      return color.map { |e| e.to_i }
    end
  end

  def self.parse_color(color)
    m = /(\d+),(\d+),(\d+)/.match(color)
    return m[1..3].map{|e| e.to_i} if m
    m = /#([a-fA-F0-9]{2})([a-fA-F0-9]{2})([a-fA-F0-9]{2})/.match(color)
    return m[1..3].map{|e| e.to_i(16)} if m
    JSON.load(color)[0..2].map{ |e| e.to_i } rescue nil
  end
  
  def self.load_color_subclass(path)
    begin
      c = eval(IO.read(path)).new
      puts "loaded Class #{c.class.name} from #{path}"
      return c
    rescue
      puts "Error in #{path}:"
      puts $!
      puts $@
    end
  end

  def self.load_colors
    @@colors = Hash[File.open('colors.txt').each_line.map do |line|
      m = /([^ ]+)\s+(#[a-fA-F0-9]{6})/.match(line)
      [m[1].downcase, parse_color(m[2])] if m
    end.compact]
  end
end

class ConstantColorProgram < ColorProgram
  def initialize(color)
    @color = color
  end

  def current
    @color
  end

  def next
  end
end

class ColorListProgram < ColorProgram
  def initialize(colors)
    @colors = colors.map { |l| ColorProgram.to_color l }
    @index = 0
    fail "Hab keine Farben!" if @colors.length == 0
  end

  def self.from_file(path)
    colors = []
    File.open(colors).each do |line|
      c = ColorProgram.to_color(line.strip)
      colors << c if c
    end
    puts "loaded Program #{colors} with #{@colors.length} lines"
    return ColorListProgram.new(colors)
  end

  def current
    return @colors[@index]
  end

  def next
    @index = (@index + 1) % @colors.length
  end
end

class EdiClient
  def initialize(dmx_control, host, routing_key_prefix)
    @dmx_control = dmx_control
    @routing_key_prefix = routing_key_prefix
    @conn = Bunny.new(:host => host)
    @conn.start
    ch = @conn.create_channel
    xchg = ch.topic("act_dmx", :auto_delete => true)
    q = ch.queue("act_dmx_subraum", :auto_delete => true)
    q.bind(xchg, :routing_key => routing_key_prefix+".*").subscribe do |info, meta, data|
      handle_message(info, meta, data)
    end
  end

  def handle_message(info, meta, data)
    rk = info.routing_key
    puts "#{rk}: #{data}"
    return unless rk.start_with?(@routing_key_prefix + ".")
    rk = rk[@routing_key_prefix.length+1..-1]
    case rk
    when "control"
      case data
      when "on" then
        @dmx_control.on
      when "off" then
        @dmx_control.off
      end
    else
      lamp = rk
      begin
        program = ColorProgram.to_color_program(data)
        puts "Setting #{lamp} to #{program}"
        @dmx_control.setprogram(lamp.to_i, program)
      rescue => err
        puts "Error while handling message with rk=#{rk.inspect}, data=#{data.inspect}: #{err}"
      end
    end
  end

  def close
    @conn.close
  end
end

config
$program_path = File.realpath($program_path)
ColorProgram.load_colors

if __FILE__ == $0
  dmx_control = DmxControl.new
  config_lamps(dmx_control)
  dmx_control.on

  edi_client = EdiClient.new(
    dmx_control,
    ENV.fetch("AMQP_SERVER", "mopp"),
    "dmx.lamp.#{$subsystem}")

  dmx_control.loop
  edi_client.close
end

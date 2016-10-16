class BackgroundD < ColorProgram
	def initialize
		@t = 0
	end

	def current
		current_at_index(0, 1)
	end

	def current_at_index(index, all_led_count)
		[((@t+index)%2)*200, (1-(@t+index)%2)*200, 0]
	end

	def next
		@t += 1
	end

	def self.new
		obj = self.allocate
		obj.send :initialize
		return RunColorOverStripe.new(obj)
	end
end
BackgroundD
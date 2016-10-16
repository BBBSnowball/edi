class BackgroundC < ColorProgram
	def initialize
		@t = 0
	end

	def current
		if @t < 1*256
			[@t, 0, 0]
		elsif @t < 2*256
			[0, @t-256, 0]
		elsif @t < 3*256
			[0, 0, @t-512]
		else
			[255, 255, 0]
		end
	end

	def next
		@t = (@t+1) % (256*3 + 30)
	end

	def self.new
		obj = self.allocate
		obj.send :initialize
		return RunColorOverStripe.new(obj)
	end
end
BackgroundC
class BackgroundA < ColorProgram
	def initialize
		@steps = [0.3, 0.5, 0.7]
		@curVal = [ 50, 0, 150 ]
		@curChange = [ @steps[0], @steps[1], -@steps[2] ];

	end
	def current
		@curVal
	end
	def next
		@curChange.each_index { |i|
			@curVal[i] = @curVal[i] + @curChange[i]
			if (@curVal[i] >= 255) then
				@curVal[i] = 255
				@curChange[i] *=  -1
			elsif (@curVal[i] <= 0) then
				@curVal[i] = 0
				@curChange[i] *= -1
				curStep = @steps.find_index(@curChange[i]) || 2
				@curChange[i] = @steps[(curStep+1) % @steps.length]
			end
		}
	end
end
BackgroundA
class Dummy < ColorProgram

	#Konstruktor ohne Argumente
	def initialize
		@bgsteps = [0.1, 0.2, -0.3]
  		@bgvals = [100, 100, 100]
	end

	#die aktuelle Farbe zurückgeben als [r,g,b] = [0-255,0-255,0-255]
	def current
		return @bgvals
	end

	#weiterschalten auf die nächste Farbe. Rückgabewert wird ignoriert
	def next
		@bgvals = @bgvals.zip(@bgsteps).map{ |a,b| (a+b)%255 }
	end
end
#am Ende die Klasse zurückgeben die als Farbe instanziiert werden soll
Dummy
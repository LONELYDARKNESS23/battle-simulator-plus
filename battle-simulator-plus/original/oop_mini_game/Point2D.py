class Point2D:
    @classmethod
    def dist(cls, a, b):
        c_x = a.x - b.x
        c_y = a.y - b.y
        return abs(Point2D(c_x, c_y))
    
    def __init__(self, x, y):
        Point2D.verify_coord(x)
        Point2D.verify_coord(y)
        self.__x = x
        self.__y = y

    @classmethod
    def verify_coord(cls, coord):
        if type(coord) != float: raise TypeError("Coordinates must be a float!")
       
    def get_position(self):
        return (self.x, self.y)
    
    @property
    def x(self):
        return self.__x
    
    @x.setter
    def x(self, new_x):
        Point2D.verify_coord(new_x)
        self.__x = new_x
        
    @property
    def y(self):
        return self.__y
    
    @y.setter
    def y(self, new_y):
        Point2D.verify_coord(new_y)
        self.__y = new_y

    def normalize(self):
        norm = (self.x * self.x + self.y * self.y)**0.5
        new_x = self.x / norm
        new_y = self.y / norm 
        return Point2D(new_x, new_y)
        
    def __add__(self, other):
        return Point2D(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other):
        return Point2D(self.x - other.x, self.y - other.y)
    
    def __mul__(self, n):
        return Point2D(self.x * n, self.y * n)
    
    def __abs__(self):
        return (self.x * self.x + self.y * self.y)**0.5




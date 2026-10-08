from doctest import Example
from ollama import chat
from Point2D import Point2D
import shlex

model_ = 'gemma4:e4b'

class Unit:
    units = []
    next_index = 0


    @classmethod
    def get_by_index(cls, index):
        for unit in cls.units:
            if unit.index == index:
                return unit
        return None
    # @classmethod
    # def search_enemy(cls, point, clan):
    #     res = None
    #     min_dist = 100
    #     for i in cls.units:
    #         if i.clan != clan and Point2D.dist(i.position, point) < min_dist:
    #             res = i
    #             min_dist = Point2D.dist(i.position, point)
    #     return res
    
    @classmethod
    def what_can_i_see(cls, point, radius):
        res = []
        for i in cls.units:
            if Point2D.dist(i.position, point) <= radius:
                res.append(i)
        res.sort(key=lambda unit: Point2D.dist(unit.position, point))
        return res

    def __init__(self, hp, damage, point, speed, clan, rad_of_vis, model = model_):
        Unit.verify_point(point)
        Unit.verify_clan(clan)
        self.index = Unit.next_index
        Unit.next_index += 1
        self.__hp_bar = hp
        self.max_hp = hp
        self.damage = damage
        self.__position = point
        self.speed = speed
        self.__clan = clan
        self.rov = rad_of_vis
        self.enemy = None
        self.context = []
        
        self.model = model
        Unit.units.append(self)
    
    @classmethod
    def verify_point(cls, point):
        if abs(point.x) >= 50 or abs(point.y) >= 50: raise ValueError("values must be in the square 20x20")
      
    @classmethod
    def verify_clan(cls, clan):
        if type(clan) != int: raise TypeError("Clan must be an integer!")

    @property
    def hp_bar(self):
        return self.__hp_bar
    
    @hp_bar.setter
    def hp_bar(self, new_hp):
        self.__hp_bar = new_hp

    @property
    def clan(self):
        return self.__clan
    
    @clan.setter
    def clan(self, new_clan):
        Unit.verify_clan(new_clan)
        self.__clan = new_clan

    @property
    def position(self):
        return self.__position
    
    @position.setter
    def position(self, new_pos):
        Unit.verify_point(new_pos)
        self.__position = new_pos
        
    def parse(self, answer):
        try:
            res = shlex.split(answer)
            if res[0] == '1':
                goal = Point2D(float(res[1]), float(res[2]))
                self.move(goal)
            if res[0] == '2':
                target = Unit.get_by_index(int(res[1]))
                if Point2D.dist(self.position, target.position) <= self.speed: 
                    self.attack(target)
            if res[0] == '3':
                if len(res[2]) <= 300:
                    self.context.append({
                        'type' : 'write', #0 - write, 1 - get
                        'with_unit' : int(res[1]),
                        'content': res[2]
                        })
                    target = Unit.get_by_index(int(res[1]))
                    target.context.append({
                        'type' : 'get', #0 - write, 1 - get
                        'with_unit' : self.index,
                        'content': res[2]
                        })
                else: print(f'Too long message. Move of Unit {self.index} was skpped')
                
                
                
        except Exception as e:
            print(f'Parsing error. Move of Unit {self.index} was skipped cause of {e}. Text: {answer}')


    def think(self, seeings): 
        dir = {
            'index' : self.index,
            'clan' : self.clan,
            'radius' : self.rov,
            'speed' : self.speed,
            'hp' : self.hp_bar,
            'position' : (self.position.x, self.position.y),
            'damage' : self.damage,
            'context' : self.context,
            'max_hp' : self.max_hp 
            }
        
        see_units = []
        for i in seeings:
            see_units.append({'index' : i.index,
                'clan' : i.clan,
                'speed' : i.speed,
                'hp' : i.hp_bar,
                'position' : (i.position.x, i.position.y),
                'damage' : i.damage,
                'distance' : Point2D.dist(i.position, self.position)
                })
        response = chat(
            model=self.model,
            messages=[{'role': 'user', 'content': f'''You are a player in a little battle simulation. It is a turn-based game, so you can choose only 1 action: move in some diraction, say something short (no more than 300 characters) to another unit or attack another unit. Your attack range is equals to your speed
                       Your id: {dir['index']}, your clan: {dir['clan']}, your hp: {dir['hp']}/{dir['max_hp']}, your speed: {dir['speed']}, your damage: {dir['damage']}, your context of messages: {dir['context']}. You are currently at point {dir['position']} and can see the following list of units: {see_units}. 
                       Give a short answer: what will you do, if it is movement - write '1 ' + 2 numbers of coordinates where you want to end up (for example - '1 20 40'), if you want to attack - write '2 'index of unt you want to attack (for example - '2 4'), if you want to write a message - write '3 ' and say to which unit you want to write the message and content of this message (for example - '3 5 "Hello!"').
                       if you would try to attack the unit you cant - your move will be skippep. DONT WRITE ANYTHING ELSE!!!'''}],
            think=False           
        )
        # print( f'''Your are player in a little battle simulation. It is step by step game, so you can choose only 1 action: move in some diraction, say something short (no more than 300 signs) to other unit or attack other unit. Your attack range is equals with your speed
        #                 Your id: {dir['index']}, your clan: {dir['clan']}, your hp: {dir['hp']}, your speed: {dir['speed']}, your damage: {dir['damage']}, your context of messages: {dir['context']}. Now you are in the point {dir['position']} and see this list of units: {see_units}. 
        #                 Give a short answer: what will you do, if it is movement - write '1 ' + 2 numbers of coordinates where you want to end up (for example - '1 20 40'), if you want to attack - write '2 'index of unt you want to attack (for example - '2 4'), if you want to write a message - write '3 ' and say to which unit you want to write the message and content of this message (for example - '3 5 "Hello!"').
        #                 if you would try to attack the unit you cant - your move will be skippep. DONT WRITE ANYTHING ELSE!!!''')
        self.parse(response.message.content)
        
        

    def move(self, goal):
        v = Point2D(goal.x - self.position.x, goal.y - self.position.y)
        if abs(v) < self.speed: 
            self.position = goal
        else:
            self.position = self.position + v.normalize() * self.speed
        
    def attack(self, victim):
        victim.hp_bar = victim.hp_bar - self.damage
        
    # def can_attack(self):
    #     if self.position == self.enemy.position: return True
    #     return False

    @classmethod
    def check(cls):
        for i in cls.units[:]: 
            if i.hp_bar <= 0: 
                Unit.units.remove(i)
                print(f"unit from clan {i.clan} died")
                del i
                for j in cls.units:
                    print(j.hp_bar, j.position.x, j.position.y)
            
                
    def check_enemy(self, enemy):
        if self.enemy == None: 
            self.enemy = Unit.search_enemy(self.position, self.clan)

    @classmethod
    def epoch(cls):
        for i in cls.units:
            seeings = Unit.what_can_i_see(i.position, i.rov)
            i.think(seeings)
            # for j in seeings: 
            #     if j.clan != i.clan: 
            #         i.enemy = j
            #         break
            # if i.enemy != None:
            #     if i.can_attack() == 0:
            #         i.move(i.enemy.position)
            #     if i.can_attack() == 1: 
            #         i.attack(i.enemy)
            cls.check()


class Archer(Unit):
    def __init__(self, hp, damage, point, speed, clan, attack_range):
        super().__init__(hp, damage, point, speed, clan)
        self.attack_range = attack_range
        
    def move(self, goal):
        v = Point2D(goal.x - self.position.x, goal.y - self.position.y)
        if abs(v) < self.speed + self.attack_range: 
            self.position = goal
        else:
            self.position = self.position + v.normalize() * self.speed
            
    def can_attack(self):
        if Point2D.dist(self.position, self.enemy.position) <= self.attack_range: return True
        return False
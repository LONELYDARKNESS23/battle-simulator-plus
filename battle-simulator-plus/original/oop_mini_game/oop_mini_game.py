from Point2D import Point2D
from Unit import Unit, Archer
import pygame

colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]

def coords_to_screen(x, y):
    s_x = (x + 50) * 10
    s_y = (y + 50) * 10
    return (s_x, s_y)

def draw_unit(screen, unit):
    x, y = coords_to_screen(unit.position.x, unit.position.y)

    color = colors[unit.clan]

    pygame.draw.circle(screen, color, (int(x), int(y)), 10)

    max_hp = unit.max_hp
    hp_width = 40
    hp_height = 5

    hp_ratio = max(0, unit.hp_bar / max_hp)

    pygame.draw.rect(
        screen,
        (100, 100, 100),
        (x - hp_width // 2, y - 20, hp_width, hp_height)
    )

    pygame.draw.rect(
        screen,
        (0, 255, 0),
        (x - hp_width // 2, y - 20,
         int(hp_width * hp_ratio), hp_height)
    )

    font = pygame.font.Font(None, 20)
    text = font.render(str(unit.index), True, (255, 255, 255))
    screen.blit(text, (x + 12, y - 10))
    
def draw_chat(screen):
    chat_x = 1000
    chat_width = 500

    pygame.draw.rect(
        screen,
        (25, 25, 25),
        (chat_x, 0, chat_width, 1000)
    )

    pygame.draw.line(
        screen,
        (100, 100, 100),
        (chat_x, 0),
        (chat_x, 1000),
        2
    )

    font = pygame.font.Font(None, 24)
    small_font = pygame.font.Font(None, 20)

    title = font.render("CHAT", True, (255, 255, 255))
    screen.blit(title, (chat_x + 20, 20))

    y = 60

    for unit in Unit.units:
        for message in unit.context:

            if message['type'] != 'get':
                continue

            sender = message['with_unit']
            receiver = unit.index
            content = message['content']

            text = f"Unit {sender} -> Unit {receiver}"

            text_surface = small_font.render(
                text,
                True,
                (180, 180, 180)
            )

            screen.blit(text_surface, (chat_x + 20, y))
            y += 22

            message_surface = small_font.render(
                content,
                True,
                (255, 255, 255)
            )

            screen.blit(message_surface, (chat_x + 30, y))
            y += 30

            if y > 970:
                return
    
unit1 = Unit(float(10), float(1), Point2D(float(1), float(1)), float(1), int(1), float(10))
unit2 = Unit(float(5), float(2), Point2D(float(14), float(17)), float(1), int(1), float(20))
unit3 = Unit(float(20), float(0.5), Point2D(float(14), float(1)), float(0.3), int(2), float(5))
unit4 = Unit(float(2), float(2), Point2D(float(7), float(12)), float(4), int(3), float(50))
unit5 = Unit(float(2), float(2), Point2D(float(7), float(13)), float(4), int(3), float(50))

pygame.init()
screen = pygame.display.set_mode((1500, 1000))
pygame.display.set_caption("Battle simulation")


running = True
epoch = 0
while running:
    screen.fill((0, 0, 0))
    
    for unit in Unit.units:
        draw_unit(screen, unit)
    draw_chat(screen)
    font = pygame.font.Font(None, 40)
    title = font.render(str(epoch), True, (255, 255, 255))
    screen.blit(title, (500, 50))
    pygame.display.update()

    Unit.epoch()
    epoch+=1
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
            pygame.quit()
            
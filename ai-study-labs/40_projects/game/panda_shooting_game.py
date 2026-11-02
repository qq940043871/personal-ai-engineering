import pygame
import random
import math

# Initialize Pygame
pygame.init()

# Game window settings
SCREEN_WIDTH = 540
SCREEN_HEIGHT = 720
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Panda Shooting Game - Panda Shooter")
clock = pygame.time.Clock()

# Color definitions
BG_COLOR = (135, 206, 250)  # Sky blue
WHITE = (255, 255, 255)

# Load resources (you need to prepare your own images or use basic shapes instead)
# Note: You need to create an images folder and put the corresponding images in it
def load_image(path, size=None):
    image = pygame.image.load(f"D:/workspace/p001_ai_study_py/08_game/panda_shooting_game/{path}").convert_alpha()
    return pygame.transform.scale(image, size) if size else image

# Game character
class Panda(pygame.sprite.Sprite):
    def __init__(self):
        super().__init__()
        self.images = {
            "idle": load_image("panda_idle.png", (80, 80)),
            "shoot": load_image("panda_shoot.png", (80, 80))
        }
        self.image = self.images["idle"]
        self.rect = self.image.get_rect(center=(SCREEN_WIDTH//2, SCREEN_HEIGHT-100))
        self.speed = 5
        self.shoot_cooldown = 0

    def update(self, keys):
        # Movement control
        if keys[pygame.K_a]:
            self.rect.x -= self.speed
        if keys[pygame.K_d]:
            self.rect.x += self.speed
        self.rect.clamp_ip(screen.get_rect())

        # Shooting cooldown
        if self.shoot_cooldown > 0:
            self.shoot_cooldown -= 1

        # Shooting animation
        if keys[pygame.K_SPACE] and self.shoot_cooldown <= 0:
            self.image = self.images["shoot"]
        else:
            self.image = self.images["idle"]

# Bullet class
class Bullet(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = load_image("bamboo_bullet.png", (30, 50))
        self.rect = self.image.get_rect(center=(x, y))
        self.speed = -5

    def update(self):
        self.rect.y += self.speed
        if self.rect.bottom < 0:
            self.kill()

# Enemy class (basic version)
class Enemy(pygame.sprite.Sprite):
    def __init__(self):
        super().__init__()
        self.image = load_image("enemy.png", (60, 60))
        self.rect = self.image.get_rect(
            center=(random.randint(30, SCREEN_WIDTH-30), -30)
        )
        self.speed = random.randint(3, 5)

    def update(self):
        self.rect.y += self.speed
        if self.rect.top > SCREEN_HEIGHT:
            self.kill()

# Game manager
class Game:
    def __init__(self):
        self.all_sprites = pygame.sprite.Group()
        self.bullets = pygame.sprite.Group()
        self.enemies = pygame.sprite.Group()
        self.panda = Panda()
        self.all_sprites.add(self.panda)
        self.score = 0
        self.enemy_spawn_rate = 30  # Enemy spawn rate

        # Load background (optional)
        self.background = load_image("forest_bg.png", (SCREEN_WIDTH, SCREEN_HEIGHT))

    def run(self):
        running = True
        while running:
            # Event handling
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    if self.panda.shoot_cooldown <= 0:
                        bullet = Bullet(self.panda.rect.centerx, self.panda.rect.top)
                        self.all_sprites.add(bullet)
                        self.bullets.add(bullet)
                        self.panda.shoot_cooldown = 15  # Shooting cooldown time

            # Update characters
            keys = pygame.key.get_pressed()
            self.panda.update(keys)
            for sprite in self.all_sprites:
                if sprite != self.panda:
                    sprite.update()

            # Generate enemies
            if random.randint(1, self.enemy_spawn_rate) == 1:
                enemy = Enemy()
                self.all_sprites.add(enemy)
                self.enemies.add(enemy)

            # Collision detection
            hits = pygame.sprite.groupcollide(self.bullets, self.enemies, True, True)
            for hit in hits:
                self.score += 10

            # Update all sprites
            # Remove the redundant call to self.all_sprites.update()

            # Draw the screen
            screen.blit(self.background, (0, 0))
            self.all_sprites.draw(screen)

            # Display the score
            font = pygame.font.Font(None, 36)
            text = font.render(f"Score: {self.score}", True, WHITE)
            screen.blit(text, (10, 10))

            pygame.display.flip()
            clock.tick(60)

        pygame.quit()

# Run the game
if __name__ == "__main__":
    game = Game()
    game.run()
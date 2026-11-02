import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
import random
import math

# 初始化Pygame
pygame.init()
display = (800, 600)
pygame.display.set_mode(display, DOUBLEBUF|OPENGL)

# 设置OpenGL视角
gluPerspective(45, (display[0]/display[1]), 0.1, 50.0)
glTranslatef(0.0, 0.0, -5)

# 球体类
class Sphere:
    def __init__(self, x, y, z, radius, color):
        self.x = x
        self.y = y
        self.z = z
        self.radius = radius
        self.color = color
        self.quadric = gluNewQuadric()
    
    def draw(self):
        glPushMatrix()
        glTranslatef(self.x, self.y, self.z)
        glColor3fv(self.color)
        gluSphere(self.quadric, self.radius, 32, 32)
        glPopMatrix()
    
    def move(self, dx, dy, dz):
        # 边界检测，限制球体不能移出显示区域
        max_pos = 3.0 - self.radius  # 最大位置减去半径
        
        new_x = self.x + dx
        new_y = self.y + dy
        new_z = self.z + dz
        
        # 限制在边界范围内
        self.x = max(-max_pos, min(max_pos, new_x))
        self.y = max(-max_pos, min(max_pos, new_y))
        self.z = max(-max_pos, min(max_pos, new_z))

# 玩家球
player = Sphere(0, 0, 0, 0.3, (0, 1, 0))
# 食物球列表
foods = []
# 分数
score = 0

# 生成随机食物球
def spawn_food():
    # 确保食物球生成在可见范围内(考虑球体半径)
    max_pos = 3.0  # 最大位置
    min_radius = 0.1
    max_radius = 0.3
    
    radius = random.uniform(min_radius, max_radius)
    x = random.uniform(-max_pos + radius, max_pos - radius)
    y = random.uniform(-max_pos + radius, max_pos - radius)
    z = random.uniform(-max_pos + radius, max_pos - radius)
    
    # 检查是否与现有球体重叠
    new_sphere = Sphere(x, y, z, radius, (0,0,0))
    for food in foods:
        if check_collision(new_sphere, food):
            # 如果重叠则重新生成
            return spawn_food()
    
    color = (random.random(), random.random(), random.random())
    foods.append(Sphere(x, y, z, radius, color))

# 碰撞检测
def check_collision(sphere1, sphere2):
    # 优化碰撞检测，使用平方距离避免开方运算
    dx = sphere1.x - sphere2.x
    dy = sphere1.y - sphere2.y
    dz = sphere1.z - sphere2.z
    min_distance = sphere1.radius + sphere2.radius
    return (dx*dx + dy*dy + dz*dz) < (min_distance * min_distance)

# 初始化食物
for i in range(5):
    spawn_food()

# 游戏主循环
clock = pygame.time.Clock()
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
    
    # 处理键盘输入
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]:
        player.move(-0.05, 0, 0)
    if keys[pygame.K_RIGHT]:
        player.move(0.05, 0, 0)
    if keys[pygame.K_UP]:
        player.move(0, 0.05, 0)
    if keys[pygame.K_DOWN]:
        player.move(0, -0.05, 0)
    if keys[pygame.K_w]:
        player.move(0, 0, -0.05)
    if keys[pygame.K_s]:
        player.move(0, 0, 0.05)
    
    # 检测碰撞并吞噬食物
    for food in foods[:]:
        if check_collision(player, food):
            if player.radius > food.radius:
                player.radius += food.radius * 0.1  # 玩家球变大
                foods.remove(food)
                score += 1
                spawn_food()  # 生成新食物
            else:
                running = False
                print("游戏结束！你的分数是:", score)
    
    # 渲染
    glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
    
    # 绘制玩家球
    player.draw()
    
    # 绘制所有食物球
    for food in foods:
        food.draw()
    
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
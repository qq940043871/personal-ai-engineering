import random
import csv

# 商品名称前缀
prefixes = ['时尚', '简约', '豪华', '经典', '智能']

# 商品类型
product_types = ['手表', '手机', '笔记本电脑', '耳机', '相机']

# 颜色选项
colors = ['黑色', '白色', '银色', '金色', '蓝色']

# 生成商品信息
def generate_products(num_products):
    products = []
    for _ in range(num_products):
        name = random.choice(prefixes) + random.choice(product_types)
        price = round(random.uniform(100, 10000), 2)
        color = random.choice(colors)
        products.append([name, price, color])
    return products

# 生成100条商品信息
products = generate_products(100)

# 输出到控制台
for product in products:
    print(f"商品名称: {product[0]}, 价格: {product[1]}, 颜色: {product[2]}")

# 保存到CSV文件
with open('products.csv', 'w', newline='', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow(['商品名称', '价格', '颜色'])
    writer.writerows(products)
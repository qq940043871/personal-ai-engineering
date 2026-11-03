import csv
import random

# 定义商品名称列表
product_names = [
    "笔记本电脑", "智能手机", "平板电脑", "智能手表", "无线耳机",
    "相机", "无人机", "智能音箱", "游戏机", "电视",
    "空调", "冰箱", "洗衣机", "微波炉", "电饭煲",
    "电烤箱", "空气净化器", "加湿器", "扫地机器人", "吸尘器",
    "按摩椅", "瑜伽垫", "健身器材", "运动鞋", "运动服",
    "背包", "钱包", "帽子", "围巾", "手套",
    "雨伞", "太阳镜", "手表", "项链", "手链",
    "戒指", "耳环", "香水", "护肤品", "彩妆",
    "洗发水", "沐浴露", "牙膏", "牙刷", "毛巾",
    "床单", "被罩", "枕套", "抱枕", "地毯",
    "窗帘", "沙发套", "椅子套", "桌子套", "地板垫",
    "书架", "电视柜", "衣柜", "鞋柜", "书桌",
    "椅子", "桌子", "办公椅", "文件柜", "白板",
    "打印机", "扫描仪", "传真机", "投影仪", "音响",
    "游戏键盘", "游戏鼠标", "游戏手柄", "游戏耳机", "游戏摄像头",
    "游戏显示器", "游戏主机", "游戏路由器", "游戏路由器", "游戏路由器"
]

# 定义颜色列表
colors = ["红色", "蓝色", "绿色", "黄色", "黑色", "白色", "灰色", "紫色", "橙色", "粉色"]

# 定义发货地列表
shipping_locations = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "重庆"]

# 生成1000条商品信息
with open('products.csv', 'w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ['商品名称', '颜色', '价格', '发货地']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

    writer.writeheader()
    for _ in range(200):
        product_name = random.choice(product_names)
        color = random.choice(colors)
        price = round(random.uniform(100, 10000), 2)  # 价格在100到10000之间，保留两位小数
        shipping_location = random.choice(shipping_locations)

        writer.writerow({
            '商品名称': product_name,
            '颜色': color,
            '价格': price,
            '发货地': shipping_location
        })
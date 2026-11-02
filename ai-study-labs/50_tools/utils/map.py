import geopandas as gpd
import matplotlib.pyplot as plt
import requests
import os
import zipfile
import tempfile
import shutil

# 从 Natural Earth 网站下载 110m 分辨率的国家边界数据
def get_world_map():
    url = 'https://www.naturalearthdata.com/http//www.naturalearthdata.com/download/110m/cultural/ne_110m_admin_0_countries.zip'
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, 'ne_110m_admin_0_countries.zip')
    
    try:
        # 下载文件
        print('正在从 Natural Earth 网站下载地图数据...')
        response = requests.get(url)
        response.raise_for_status()
        
        # 保存压缩文件
        with open(zip_path, 'wb') as f:
            f.write(response.content)
        
        # 解压文件
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # 查找 shapefile
        shapefile_path = None
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.shp'):
                    shapefile_path = os.path.join(root, file)
                    break
            if shapefile_path:
                break
        
        if not shapefile_path:
            raise FileNotFoundError('未找到 shapefile')
        
        # 读取数据
        world = gpd.read_file(shapefile_path)
        return world
    
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)

# 获取世界国家地理数据
print('开始绘制东盟国家地图...')
world = get_world_map()

# 2. 定义东盟10国的英文名（与Natural Earth数据集匹配）
asean_countries = [
    'Brunei', 'Cambodia', 'Indonesia', 'Laos', 'Malaysia',
    'Myanmar', 'Philippines', 'Singapore', 'Thailand', 'Vietnam'
]

# 3. 筛选东盟国家数据（使用NAME字段，这是Natural Earth数据集中的标准字段名）
asean = world[world['NAME'].isin(asean_countries)]

# 4. 绘制地图
fig, ax = plt.subplots(figsize=(10, 8))

# 绘制东盟国家（填充颜色）
asean.plot(ax=ax, color='lightblue', edgecolor='black', linewidth=0.8)

# 绘制世界其他国家（灰色背景，突出东盟）
world[~world['NAME'].isin(asean_countries)].plot(ax=ax, color='lightgray', edgecolor='white', linewidth=0.3)

# 添加国家名称标签
for idx, row in asean.iterrows():
    # 计算国家几何中心作为标签位置
    centroid = row['geometry'].centroid
    ax.text(centroid.x, centroid.y, row['NAME'], fontsize=8, ha='center')

# 设置标题和坐标轴
ax.set_title('ASEAN 10 Member States', fontsize=15)
ax.set_axis_off()  # 隐藏坐标轴

# 调整布局并显示
plt.tight_layout()
plt.show()
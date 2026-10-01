import plotly.express as px
import pandas as pd

# 1. 定义东盟10国的ISO 3166-1 alpha-3代码（国际标准国家代码）
asean_data = pd.DataFrame({
    '国家': ['文莱', '柬埔寨', '印度尼西亚', '老挝', '马来西亚',
            '缅甸', '菲律宾', '新加坡', '泰国', '越南'],
    '代码': ['BRN', 'KHM', 'IDN', 'LAO', 'MYS',
            'MMR', 'PHL', 'SGP', 'THA', 'VNM'],
    '数值': [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]  # 可替换为实际数据（如人口、GDP等）
})

# 2. 绘制交互式地图
fig = px.choropleth(
    asean_data,
    locations='代码',  # 国家代码列
    locationmode='ISO-3',  # 使用ISO 3166-1代码匹配
    color='数值',  # 用于着色的列（此处仅为区分）
    hover_name='国家',  # 悬停时显示的名称
    color_continuous_scale='Viridis',  # 颜色方案
    title='东盟10国地图（交互式）'
)

# 调整地图视角（聚焦东南亚）
fig.update_geos(
    center=dict(lon=105, lat=15),  # 东南亚中心经纬度
    scope='asia',  # 限制地图范围为亚洲区域，自动聚焦
    resolution=50  # 提高地图分辨率
)

# 显示地图
fig.show()
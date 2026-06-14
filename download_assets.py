import urllib.request
import os

# 确保目录存在
os.makedirs('assets/web', exist_ok=True)

# 需要下载的静态资源 (使用国内可访问的备用 CDN 或官方源)
files = {
    'markdown-it.min.js': 'https://unpkg.com/markdown-it@13.0.1/dist/markdown-it.min.js',
    'highlight.min.js': 'https://unpkg.com/@highlightjs/cdn-assets@11.9.0/highlight.min.js',
    'github-dark.min.css': 'https://unpkg.com/@highlightjs/cdn-assets@11.9.0/styles/github-dark.min.css'
}

for name, url in files.items():
    print(f"正在下载 {name} ...")
    try:
        urllib.request.urlretrieve(url, f'assets/web/{name}')
        print(f"✅ {name} 下载成功")
    except Exception as e:
        print(f"❌ {name} 下载失败: {e}")

print("\n资源准备完毕！")
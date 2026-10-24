# 生成一套假照片（只有 EXIF 时间/位置/设备）用于测试：北京常住 + 新疆/承德自驾 + 美西 + 澳洲 + 东京
# 用法：python tests/make_sample.py 输出文件夹（需要 exiftool；可用环境变量 EXIFTOOL 指定路径）
import random, datetime as dt, os, subprocess, shutil, sys
from PIL import Image
OUT=sys.argv[1]; random.seed(2); os.makedirs(OUT,exist_ok=True)
base=os.path.join(OUT,'.base.jpg'); Image.new('RGB',(320,240),(120,160,200)).save(base,quality=60)
args=[]; i=0
def add(folder, when, model, make, gps=None):
    global i
    d=os.path.join(OUT,folder); os.makedirs(d,exist_ok=True)
    p=os.path.join(d,f'IMG_{i:05d}.JPG'); i+=1; shutil.copy(base,p)
    a=[f'-DateTimeOriginal={when:%Y:%m:%d %H:%M:%S}',f'-Model={model}',f'-Make={make}']
    if gps:
        la,lo=gps; a+=[f'-GPSLatitude={abs(la)}',f'-GPSLatitudeRef={"N" if la>=0 else "S"}',f'-GPSLongitude={abs(lo)}',f'-GPSLongitudeRef={"E" if lo>=0 else "W"}']
    args.append((p,a))
HOME=(39.93,116.42)
# 自驾：每天一段，从 a 到 b，9 点到 18 点每小时一张
road=[(dt.date(2022,7,10),[(43.8,87.6),(44.3,86.05),(45.6,84.9),(47.7,88.1),(48.7,87.0),(47.2,89.6),(44.1,87.9),(43.8,87.6)]),
      (dt.date(2023,10,1),[(36.17,-115.14),(37.2,-112.98),(36.91,-111.46),(36.06,-112.14),(35.19,-114.05),(34.05,-118.24),(35.37,-120.85),(36.6,-121.9),(37.77,-122.42)]),
      (dt.date(2024,5,1),[(-37.81,144.96),(-38.34,143.59),(-38.68,143.39),(-38.66,143.1),(-37.56,143.85),(-37.81,144.96)]),
      (dt.date(2021,10,1),[(39.93,116.42),(40.97,117.94),(41.95,117.75),(42.3,118.9),(40.0,119.6),(39.93,116.42)])]
trip_days={}
for s,pts in road:
    for k,(a,b) in enumerate(zip(pts,pts[1:])):
        trip_days[s+dt.timedelta(days=k)]=(a,b)
day=dt.date(2021,1,1)
while day<=dt.date(2024,6,30):
    seg=trip_days.get(day)
    if seg:
        a,b=seg
        for h in range(10):
            u=h/9; t=dt.datetime.combine(day,dt.time(9+h,random.randint(0,50)))
            g=(a[0]+(b[0]-a[0])*u+random.uniform(-.01,.01),a[1]+(b[1]-a[1])*u+random.uniform(-.01,.01))
            add(f'iPhone/{day.year}',t,'iPhone 15 Pro','Apple',g)
            add(f'相机/{day.year}',t+dt.timedelta(minutes=2),'X100V','FUJIFILM')
    elif random.random()<0.4:
        t=dt.datetime.combine(day,dt.time(random.randint(8,21),random.randint(0,59)))
        add(f'iPhone/{day.year}',t,'iPhone 15 Pro','Apple',(HOME[0]+random.uniform(-.1,.1),HOME[1]+random.uniform(-.1,.1)))
    day+=dt.timedelta(days=1)
# 一次飞机城市游：东京
for k in range(4):
    for h in range(9,18,2):
        add('iPhone/2023',dt.datetime(2023,4,1+k,h,10),'iPhone 15 Pro','Apple',(35.68+random.uniform(-.05,.05),139.7+random.uniform(-.05,.05)))
af=os.path.join(OUT,'.argfile')
with open(af,'w') as f:
    for p,a in args: f.write('\n'.join(a+['-overwrite_original',p,'-execute'])+'\n')
subprocess.run([os.environ.get('EXIFTOOL','exiftool'),'-q','-q','-@',af],stdout=subprocess.DEVNULL)
print(len(args))
os.remove(base); os.remove(af)

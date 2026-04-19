# Pet System Module

**宠物系统模块** - 龙虾宝宝虚拟宠物

## Structure

```
pet_system/
├── pet_system.py       # 宠物系统主类
├── models.py           # 数据模型
├── subsystems/         # 子系统
│   ├── base.py         # 子系统基类
│   ├── health_system.py
│   ├── hunger_system.py
│   ├── mood_system.py
│   ├── energy_system.py
│   ├── love_system.py
│   ├── gene_system.py
│   ├── skin_system.py
│   ├── social_system.py
│   ├── diary_system.py
│   ├── dream_system.py
│   ├── personality_system.py
│   └── sound_system.py
└── utils/
    ├── storage.py
    └── formatters.py
```

## Usage

```python
from core.pet_system import get_pet_system
pet = get_pet_system()
pet.feed(20)
pet.play()
```

## Key Classes

- `PetSystem` - 宠物系统主类
- `HealthSystem` - 健康管理
- `HungerSystem` - 饥饿管理
- `MoodSystem` - 心情管理
- `EnergySystem` - 活力管理
- `LoveSystem` - 爱心系统
- `GeneSystem` - 基因系统
- `DiarySystem` - 日记系统
- `DreamSystem` - 梦境系统

## 功能

- 宠物属性管理 (心情、饱食、活力、健康、爱心)
- 经验值与升级
- 喂食、玩耍互动
- 基因遗传系统
- 日记记录
- 梦境生成

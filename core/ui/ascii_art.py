# -*- coding: utf-8 -*-
"""
ASCII 艺术库 - 多角色形象系统

提供多种可爱的 ASCII Art 角色形象，用于 CLI 界面装饰。
支持 lobster(龙虾), shrimp(小虾米), crab(小螃蟹), cat(猫猫), chick(小鸡)
"""

from __future__ import annotations

from typing import Dict, Type


# ==================== 龙虾 ASCII Art ====================
class LobsterASCII:
    """龙虾 ASCII Art 艺术库"""

    HAPPY = r"""
  (\ /)
  ( ^.^)
   >^<
  /| |\
  (_|_)
"""

    THINKING = r"""
  (\ /)
  ( ???)
   >?<
  /| |\
  (_|_)
"""

    WORKING = r"""
  (\ /)
  ( *.*)
   >~<
  /| |\
  (_|_)
"""

    SLEEPING = r"""
  (\ /)
  ( ---)
   >z<
  /| |\
  (_|_)
"""

    SURPRISED = r"""
  (\ /)
  ( O.O)
   >!<
  /| |\
  (_|_)
"""

    SUCCESS = r"""
  (\ /)
  ( ^o^)
   >v<
  /| |\
  (_|_)
"""

    SAD = r"""
  (\ /)
  ( T.T)
   >.<
  /| |\
  (_|_)
"""

    LOVE = r"""
  (\ /)
  (<3<3)
   >^<
  /| |\
  (_|_)
"""

    TINY = r"""
 (\ /)
 (^o^)
"""

    DIVIDER = "─" * 70

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        """生成 Banner"""
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 小虾米 ASCII Art ====================
class ShrimpASCII:
    """小虾米 ASCII Art - Q萌跳跃版"""

    HAPPY = r"""
     /\..{
    /  \  )~
   |    \( (
    \    ) )
     \  ( (
      \__|__\
       \ `  /
       /`-'/
      '..'
"""

    THINKING = r"""
     /\..{
    /  \  )~
   |    \( (
    \    ) )
     \  ( (
      \__|__\
       \.-./
        /V\
       / | \
"""

    WORKING = r"""
     /\..{
    /  \  )~
   |    \( *_*) 
    \    ) )
     \  ( (
      \__|__\
       \***/
       /`-`\
      '..'
"""

    SLEEPING = r"""
     /\..{
    /  \  )~
   |    \( - ) 
    \    ) )
     \  ( (
      \__|__\
       \   /
       /`-`\
      '..'
     zzZZ
"""

    SURPRISED = r"""
     /\..{
    /  \  )~
   |    \( O_O) 
    \    ) )
     \  ( (
      \__|__\
       \ ! /
       /`-'/
      '..'
"""

    SUCCESS = r"""
     /\..{
    /  \  )~
   |    \( ^o^) 
    \    ) )
     \  ( (
      \__|__\
       \ * /
       /`-'\
      '..' *
"""

    SAD = r"""
     /\..{
    /  \  )~
   |    \( T_T) 
    \    ) )
     \  ( (
      \__|__\
       \ ` /
       /`-`\
      '..'
"""

    LOVE = r"""
     /\..{
    /  \  )~
   |    \( <3<3) 
    \    ) )
     \  ( (
      \__|__\
       \ * /
       /`-'\
      '..'
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 小螃蟹 ASCII Art ====================
class CrabASCII:
    """小螃蟹 ASCII Art - 简洁卡通版"""

    HAPPY = r"""
    ,----,
   /  o o  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    THINKING = r"""
    ,----,
   /  ? ?  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    WORKING = r"""
    ,----,
   /  * *  \
  |   ~~   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    SLEEPING = r"""
    ,----,
   /  - -  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
    zzZZ
"""

    SURPRISED = r"""
    ,----,
   /  O O  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    SUCCESS = r"""
    ,----,
   /  ^ ^  \
  |   \/   |
  |  (  )  |
   \  ||  /
    '----' *
   /|    |\
  / |    | \
"""

    SAD = r"""
    ,----,
   /  x x  \
  |   __   |
  |  (  )  |
   \  \/  /
    '----'
   /|    |\
  / |    | \
"""

    LOVE = r"""
    ,----,
   /  < >  \
  |   \/   |
  |  (  )  |
   \  ||  /
    '----' *
   /|    |\
  / |    | \
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 猫猫 ASCII Art ====================
class CatASCII:
    """猫猫 ASCII Art - 可爱猫猫机器人版"""

    HAPPY = r"""
   /\_____/\
  /  o   o  \
 ( ==  ^  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    THINKING = r"""
   /\_____/\
  /  o   o  \
 ( ==  ?  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    WORKING = r"""
   /\_____/\
  /  *   *  \
 ( ==  <  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    SLEEPING = r"""
   /\_____/\
  /  -   -  \
 ( ==  -  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
    zzZ
"""

    SURPRISED = r"""
   /\_____/\
  /  O   O  \
 ( ==  !  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    SUCCESS = r"""
   /\_____/\
  /  ^   ^  \
 ( ==  w  == )
  \  ._.  /
   `----' *
  /|    |\
 / |    | \
"""

    SAD = r"""
   /\_____/\
  /  x   x  \
 ( ==  ;  == )
  \  ._.  /
   `----'
  /|    |\
 / |    | \
"""

    LOVE = r"""
   /\_____/\
  /  <   >  \
 ( ==  w  == )
  \  ._.  /
   `----' *
  /|    |\
 / |    | \
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 小鸡 ASCII Art ====================
class ChickASCII:
    """小鸡 ASCII Art - 圆润温暖版"""

    HAPPY = r"""
     _  _
    ( \/ )
    ( o.o )
    (  >  )
   /|    |\
  / |    | \
"""

    THINKING = r"""
     _  _
    ( \/ )
    ( o.o )
    (  ?  )
   /|    |\
  / |    | \
"""

    WORKING = r"""
     _  _
    ( \/ )
    ( *.* )
    (  <  )
   /|    |\
  / |    | \
"""

    SLEEPING = r"""
     _  _
    ( \/ )
    ( -. )
    (  ~  )
   /|    |\
  / |    | \
    zzZ
"""

    SURPRISED = r"""
     _  _
    ( \/ )
    ( O.O )
    (  !  )
   /|    |\
  / |    | \
"""

    SUCCESS = r"""
     _  _
    ( \/ )
    ( ^o^ )
    (  v  )
   /|    |\ *
  / |    | \
"""

    SAD = r"""
     _  _
    ( \/ )
    ( T_T )
    (  .  )
   /|    |\
  / |    | \
"""

    LOVE = r"""
     _  _
    ( \/ )
    ( <3<3)
    (  >  )
   /|    |\ *
  / |    | \
"""

    DIVIDER = "~" * 35

    @classmethod
    def get_status_art(cls, status: str) -> str:
        status_map = {
            "happy": cls.HAPPY,
            "thinking": cls.THINKING,
            "working": cls.WORKING,
            "sleeping": cls.SLEEPING,
            "surprised": cls.SURPRISED,
            "success": cls.SUCCESS,
            "sad": cls.SAD,
            "error": cls.SAD,
            "love": cls.LOVE,
        }
        return status_map.get(status.lower(), cls.HAPPY)

    @classmethod
    def get_banner(cls, name: str = "Baby", version: str = "v1.0", pet_data: dict = None) -> str:
        return _make_simple_banner(name, version, pet_data)

    @classmethod
    def get_welcome_art(cls) -> str:
        return cls.HAPPY


# ==================== 通用 Banner 生成 ====================
def _make_simple_banner(name: str, version: str, pet_data: dict = None) -> str:
    """生成简洁的 Banner（跨终端兼容的 ASCII 边框）"""
    if pet_data is None:
        pet_data = {}

    level = pet_data.get('level', 1)
    mood = pet_data.get('mood', 100)
    hunger = pet_data.get('hunger', 100)
    energy = pet_data.get('energy', 100)
    health = pet_data.get('health', 100)
    love = pet_data.get('love', 100)
    exp = pet_data.get('exp', 0)
    exp_to_next = pet_data.get('exp_to_next', 100)

    age = level - 1

    mood_emoji = "😊" if mood > 70 else "😐" if mood > 40 else "😢"
    hunger_emoji = "🍖" if hunger > 70 else "🍽️" if hunger > 40 else "😫"
    energy_emoji = "⚡" if energy > 70 else "💤" if energy > 40 else "🥱"
    health_emoji = "❤️" if health > 70 else "💔" if health > 40 else "🏥"
    love_emoji = "💕" if love > 70 else "💗" if love > 40 else "💔"

    exp_percent = exp / exp_to_next if exp_to_next > 0 else 0
    exp_bar = "#" * int(exp_percent * 6) + "-" * (6 - int(exp_percent * 6))

    # 使用 ASCII 边框字符，兼容所有终端
    lines = [
        "",
        "  +----------------------------------------------------+",
        "  |  {} {}                                      |".format(name, version),
        "  |  {}心情:{:3}/100  {}饱食:{:3}/100  {}活力:{:3}/100  |".format(
            mood_emoji, mood, hunger_emoji, hunger, energy_emoji, int(energy)),
        "  |  {}健康:{:3}/100  {}爱心:{:3}/100  经验:[{}]  |".format(
            health_emoji, health, love_emoji, love, exp_bar),
        "  |  Lv.{} (年龄:{}岁)                                |".format(level, age),
        "  +----------------------------------------------------+",
        "",
    ]

    return "\n".join(lines)


# ==================== 形象管理器 ====================
class AvatarManager:
    """ASCII 形象管理器"""

    PRESETS: Dict[str, Type] = {
        "lobster": LobsterASCII,
        "shrimp": ShrimpASCII,
        "crab": CrabASCII,
        "cat": CatASCII,
        "chick": ChickASCII,
    }

    PRESET_INFO = {
        "lobster": {"name": "龙虾宝宝", "icon": "🦞", "desc": "经典龙虾形象"},
        "shrimp": {"name": "小虾米", "icon": "🦐", "desc": "Q萌跳跃小虾"},
        "crab": {"name": "小螃蟹", "icon": "🦀", "desc": "简洁卡通螃蟹"},
        "cat": {"name": "猫猫", "icon": "🐱", "desc": "可爱猫猫机器人"},
        "chick": {"name": "小鸡", "icon": "🐣", "desc": "圆润温暖小鸡"},
    }

    def __init__(self, preset: str = "lobster"):
        self.current = self.PRESETS.get(preset, LobsterASCII)
        self.preset_name = preset

    def get_art(self, status: str) -> str:
        """根据状态获取 ASCII Art"""
        return self.current.get_status_art(status)

    def get_banner(self, name: str = None, version: str = "v1.0", pet_data: dict = None) -> str:
        """生成 Banner"""
        if name is None:
            name = self.PRESET_INFO.get(self.preset_name, {}).get("name", "Baby")
        return self.current.get_banner(name, version, pet_data)

    def get_welcome_art(self) -> str:
        """获取欢迎 ASCII Art"""
        return self.current.get_welcome_art()

    def switch(self, preset: str) -> bool:
        """切换形象"""
        if preset in self.PRESETS:
            self.current = self.PRESETS[preset]
            self.preset_name = preset
            return True
        return False

    def list_presets(self) -> Dict[str, dict]:
        """列出所有可用形象"""
        return self.PRESET_INFO.copy()


# 全局形象管理器实例
_avatar_manager: AvatarManager = None


def get_avatar_manager(preset: str = None) -> AvatarManager:
    """获取全局形象管理器"""
    global _avatar_manager
    if _avatar_manager is None:
        _avatar_manager = AvatarManager(preset or "lobster")
    elif preset:
        _avatar_manager.switch(preset)
    return _avatar_manager


def get_lobster_banner(name: str = "Baby Claw", version: str = "v1.0", pet_data: dict = None) -> str:
    """生成 Banner（兼容旧接口）"""
    return get_avatar_manager().get_banner(name, version, pet_data)


def get_status_lobster(status: str) -> str:
    """根据状态获取形象（兼容旧接口）"""
    return get_avatar_manager().get_art(status)


# 保留旧的全局常量（兼容）
LOBSTER_HAPPY = LobsterASCII.HAPPY
LOBSTER_THINKING = LobsterASCII.THINKING
LOBSTER_WORKING = LobsterASCII.WORKING
LOBSTER_SLEEPING = LobsterASCII.SLEEPING
LOBSTER_SURPRISED = LobsterASCII.SURPRISED
LOBSTER_SUCCESS = LobsterASCII.SUCCESS
LOBSTER_SAD = LobsterASCII.SAD
LOBSTER_LOVE = LobsterASCII.LOVE

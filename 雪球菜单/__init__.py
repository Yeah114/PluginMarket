import time
import traceback
from typing import Literal
from collections.abc import Callable
from dataclasses import dataclass
from tooldelta import (
    Plugin,
    cfg,
    utils,
    fmts,
    game_utils,
    TYPE_CHECKING,
    Player,
    plugin_entry,
)

import threading

_source_lock = threading.Lock()
snowmenu_lock_list: list[str] = []
# class AcquiredLock:
#     def __init__(self, sys: "SnowMenu"):
#         self.sys = sys
#     def __enter__(self):
#         self.sys._dbg("[L] Acquring lock..")
#         _source_lock.acquire()
#         self.sys._dbg("[L] Acquring lock..ok")
#     def __exit__(self, a, b, c):
#         _source_lock.release()
#         self.sys._dbg("[L] Releasing lock.")
DBG_MODE = False


@dataclass
class Page:
    """
    雪球菜单静态页面类
    Args:
        page_id: 菜单页面的ID, 不要与其他页面的id重复
        next_page_id: 下一页的ID, 玩家在扔了一次雪球之后会跳转到这个ID对应的页面
        page_texts: 这个雪球菜单页面向玩家显示的actionbar文字
        ok_cb: 玩家抬头确认选项后的回调 (玩家名: str, 当前所在页数: int) -> 需要的返回值如下:
            Page 对象: 跳转到该静态页
            元组 (MultiPage对象, <页码数: int>): 跳转到该复合页的该页码
            True: 留在该页不退出菜单
            None: 直接退出菜单
        exit_cb: 玩家低头退出菜单后的回调 (玩家名: str) -> None
        leave_cb: 玩家退出游戏后的回调 (玩家名: str) -> None
        parent_page_id: 如果这个页面是一个子页面, 则玩家低头后会跳转到父页面, 如果为 None 则直接退出菜单
    """

    page_id: str
    next_page_id: str
    page_texts: str
    ok_cb: Callable[[str], bool]
    exit_cb: Callable[[str], None] = lambda _: None
    leave_cb: Callable[[str], None] = lambda _: None
    parent_page_id: str | None = ""


@dataclass
class MultiPage:
    """
    雪球菜单动态复合页面类
    Args:
        page_id: 菜单页面的ID, 不要与其他页面的id重复
        page_cb: 显示动态菜单页的方法: (玩家名: str, 当前页码数: int) -> 需要的返回值如下:
           str: 菜单页文本内容
           None: 表示此页不存在, 将自动跳转回第一页(page_id=0)
        ok_cb: 玩家抬头确认选项后的回调 (玩家名: str, 当前所在页数: int) -> 需要的返回值如下:
            Page 对象: 跳转到该静态页
            元组 (MultiPage对象, <页码数: int>): 跳转到该复合页的该页码
            True: 留在该页不退出菜单
            None: 直接退出菜单
        exit_cb: 玩家低头退出菜单后的回调 (玩家名: str) -> None
        leave_cb: 玩家退出游戏后的回调 (玩家名: str) -> None
        parent_page_id: 如果这个页面是一个子页面, 则玩家低头后会跳转到父页面, 如果为 None 则直接退出菜单
    """

    page_id: str
    page_cb: Callable[[str, int], str | None]
    ok_cb: Callable[[str, int], None | Literal[True] | "Page" | tuple["MultiPage", int]]
    exit_cb: Callable[[str], bool | None] = lambda _: None
    leave_cb: Callable[[str], bool | None] = lambda _: None
    parent_page_id: str | None = None


PAGE_OBJ = Page | MultiPage
"菜单类"
PAGE_DISPLAY_OBJ = str | Callable[[str, int], str | None]
"显示菜单页"
menu_patterns = [0, "undefined", "undefined", "undefined", "undefined"]
"菜单最大页码数, 菜单头, 菜单选项-未被选中, 菜单选项-被选中, 菜单尾"
main_page_menus: list[
    tuple[PAGE_OBJ | Callable[[str], bool], str | Callable[[str], str]]
] = []
"主菜单: 菜单类/菜单cb, 显示字(字符串 or 显示回调)"


def default_page_show(player: str, page: int):
    max_length = len(main_page_menus)
    if page > max_length - 1:
        return None
    fmt_kws = {"[当前页码]": page + 1, "[总页码]": max_length, "[玩家名]": player}
    show_texts = [utils.simple_fmt(fmt_kws, menu_patterns[1])]
    c = page // menu_patterns[0]
    cur_pages = main_page_menus[c * menu_patterns[0] : (c + 1) * menu_patterns[0]]
    for i in cur_pages:
        if isinstance(i[1], str):
            text = i[1]
        else:
            text = i[1](player)
        show_texts.append(
            utils.simple_fmt(
                {"[选项文本]": text},
                menu_patterns[3 if page == main_page_menus.index(i) else 2],
            )
        )
    if len(show_texts) == 1:
        show_texts.append(" §7腐竹很懒, 还没有设置菜单项哦~")
    show_texts.append(utils.simple_fmt(fmt_kws, menu_patterns[4]))
    return "\n".join(show_texts)


def default_page_okcb(player: str, page: int):
    page_cb = main_page_menus[page][0]
    if isinstance(page_cb, Page):
        return page_cb
    elif isinstance(page_cb, MultiPage):
        return page_cb, 0
    else:
        return page_cb(player) or None


default_page = MultiPage("default", default_page_show, default_page_okcb)


class SnowMenu(Plugin):
    name = "雪球菜单v2"
    author = "SuperScript/chfwd"
    version = (0, 1, 7)
    description = (
        "贴合租赁服原汁原味的雪球菜单！ 可以自定义雪球菜单内容， 同时也是一个API插件"
    )
    "使用 self.GetPluginAPI('雪球菜单v2').Page 来获取到这个菜单类, 下同"
    Page = Page
    MultiPage = MultiPage

    def __init__(self, f):
        super().__init__(f)
        self.reg_pages: dict[str, PAGE_OBJ] = {"default": default_page}
        self.in_snowball_menu: dict[str, PAGE_OBJ] = {}
        "玩家名 -> 雪球菜单页类"
        self.multi_snowball_page: dict[str, int] = {}
        "玩家名 -> 多页菜单页数"
        self.default_page = "default"
        self.read_cfg()
        self.ListenPreload(self.on_def)
        self.ListenActive(self.on_inject)
        self.ListenPlayerJoin(self.on_player_join)
        self.ListenPlayerLeave(self.on_player_leave)

    # ---------------- API ------------------
    def add_page(self, page: Page | MultiPage):
        """
        向雪球菜单添加一个页码
        Args:
            page: 雪球菜单页类
        """
        self.reg_pages[page.page_id] = page

    def register_main_page(
        self,
        page_cb: PAGE_OBJ | Callable[[str], bool],
        usage_text: str | Callable[[str], str],
    ):
        """
        注册一个雪球菜单首页跳转链接
        确切来说就是让你的菜单页可以在雪球菜单首页被发现并被跳转
        或者直接注册一个雪球菜单功能
        Args:
            page_cb: 静态菜单页类 / 动态菜单页类 / 回调方法 (玩家名: str -> 确认选项后是否不关闭菜单: bool)
            usage_text: 选项的显示文本
        """
        if not isinstance(page_cb, Page | MultiPage) and not callable(page_cb):
            raise ValueError(f"注册的不是一个正常的菜单页 / 菜单回调: {page_cb}")
        main_page_menus.append((page_cb, usage_text))

    def simple_select(
        self,
        player: str,
        disp_func: Callable[[str, int], str | None],
        default_page: int = 0,
    ) -> int | None:
        """
        简单地使用雪球菜单选择选项, 返回所选择的选项(页数), 首页是第 0 页.
        Args:
            player: 玩家名
            disp_func:
                回调方法 (玩家名, 当前页数) -> 菜单显示内容 | None
                    如果返回None, 则视为需要返回第 0 页
            default_page: 打开选项后的默认页数, 默认为 0
        返回:
            选项(页数)
            None: 玩家低头取消了菜单 / 玩家中途退出.
        """
        if player not in self.game_ctrl.allplayers:
            return None
        self.game_ctrl.sendwocmd(f"/execute as @a[name={player}] at @s run tp ~~~~ 0")

        class _cb:
            def __init__(self):
                self.event = threading.Event()
                self._end = False

            def start(self):
                # 不直接 wait() 的原因是
                # ToolDeltaThread.stop() 并不能正确终止 wait() 的等待
                # 我们需要使用 while 使得 stop() 生效
                while not self._end:
                    self.event.wait(10)
                return self.page

            def ok(self, _, page):
                self.page = page
                self.event.set()
                self._end = True
                return True

            def exit(self, _):
                self.page = None
                self.event.set()
                self._end = True

        cb = _cb()
        page = MultiPage(
            page_id=f"simple-select({player},{disp_func}..)",
            page_cb=disp_func,
            ok_cb=cb.ok,
            exit_cb=cb.exit,
            leave_cb=cb.exit,
        )
        old_page = self.in_snowball_menu.get(player)
        self.set_player_page(player, page, default_page)
        if old_page is None:
            self.show_page_thread(player)
        res = cb.start()
        self.set_player_page(player, old_page)
        return res

    def simple_select_dict(self, player: str, mapping: dict[int, str]):
        """
        简单地使用雪球菜单选择选项, 返回所选择的选项(页数), 首页是第 0 页.
        Args:
            player: 玩家名
            mapping:
                页数:展示内容 dict (必须要有第零页, 即 {0: <内容>})
        返回:
            选项(页数)
            None: 玩家低头取消了菜单 / 玩家中途退出.
        """
        self.game_ctrl.sendwocmd(f"/execute as @a[name={player}] at @s run tp ~~~~ 0")

        class _cb:
            def __init__(self):
                self.event = threading.Event()
                self._end = False

            def start(self):
                # 不直接 wait() 的原因是
                # ToolDeltaThread.stop() 并不能正确终止 wait() 的等待
                # 我们需要使用 while 使得 stop() 生效
                while not self._end:
                    self.event.wait(10)
                return self.page

            def ok(self, _, page):
                self.page = page
                self.event.set()
                self._end = True
                return True

            def exit(self, _):
                self.page = None
                self.event.set()
                self._end = True

        cb = _cb()

        def page_cb(_, now_page):
            return mapping.get(now_page)

        page = MultiPage(
            page_id=f"simple-select({player},{next(iter(mapping.keys()))}..)",
            page_cb=page_cb,
            ok_cb=cb.ok,
            exit_cb=cb.exit,
            leave_cb=cb.exit,
        )
        old_page = self.in_snowball_menu.get(player)
        self._dbg(f"{player} entered dict sel")
        self.set_player_page(player, page)
        if old_page is None:
            self.show_page_thread(player)
        result = cb.start()
        self._dbg(f"{player} sel page {result}")
        self.set_player_page(player, old_page)
        return result

    # ---------------------------------------
    def on_def(self):
        self.getPosXYZ = self.GetPluginAPI("基本插件功能库", (0, 0, 7)).getPosXYZ_Int
        self.interact = self.GetPluginAPI("前置-世界交互", (0, 0, 2))
        chatbar = self.GetPluginAPI("聊天栏菜单")
        cb2bot = self.GetPluginAPI("Cb2Bot通信")
        if TYPE_CHECKING:
            from 前置_世界交互 import GameInteractive
            from 前置_聊天栏菜单 import ChatbarMenu
            from 前置_Cb2Bot通信 import TellrawCb2Bot

            self.getPosXYZ = game_utils.getPosXYZ
            self.interact: GameInteractive
            chatbar: ChatbarMenu
            cb2bot: TellrawCb2Bot
        chatbar.add_new_trigger(
            ["snowmenu-init"],
            [],
            "初始化雪球菜单所需命令方块",
            self.place_cbs,
            op_only=True,
        )
        cb2bot.regist_message_cb(
            "snowball.menu.use", lambda args: self.next_page(args[0])
        )
        cb2bot.regist_message_cb(
            "snowball.menu.escape", lambda args: self.menu_escape(args[0])
        )
        cb2bot.regist_message_cb(
            "snowball.menu.confirm", lambda args: self.menu_confirm(args[0])
        )

    def on_player_join(self, playerf: Player):
        player = playerf.name
        self.game_ctrl.sendwocmd(f"/tag @a[name={player}] remove snowmenu")

    def on_inject(self):
        self.game_ctrl.sendwocmd("/tag @a remove snowmenu")

    def set_player_page(
        self, player: str, page: Page | MultiPage | None, page_sub_id: int = 0
    ):
        if page is None:
            self.game_ctrl.sendwocmd(
                f"/tag {utils.to_player_selector(player)} remove snowmenu"
            )
            if player in self.in_snowball_menu.keys():
                del self.in_snowball_menu[player]
            if player in self.multi_snowball_page.keys():
                del self.multi_snowball_page[player]
        else:
            if player not in self.in_snowball_menu.keys():
                self.game_ctrl.sendwocmd(
                    f"/tag {utils.to_player_selector(player)} add snowmenu"
                )
            self.in_snowball_menu[player] = page
            if isinstance(page, MultiPage):
                self.multi_snowball_page[player] = page_sub_id

    def on_player_leave(self, playerf: Player):
        player = playerf.name
        if player in self.in_snowball_menu.keys():
            cb = self.in_snowball_menu[player].leave_cb
            if cb is not None:
                cb(player)
            self.remove_player_in_menu(player)

    def read_cfg(self):
        CFG_STD = {
            "单页最大选项数": int,
            "菜单退出提示": str,
            "菜单主界面格式头": str,
            "菜单主界面格式尾": str,
            "菜单主界面选项格式(选项未选中)": str,
            "菜单主界面选项格式(选项被选中)": str,
            "自定义主菜单内容": cfg.JsonList(
                {"显示名": str, "执行的指令": cfg.JsonList(str)}
            ),
        }
        CFG_DEFAULT = {
            "单页最大选项数": 6,
            "菜单退出提示": "§c已退出菜单.",
            "菜单主界面格式头": "§f雪球菜单§7> ",
            "菜单主界面格式尾": "§f - [[当前页码]/[总页码]]",
            "菜单主界面选项格式(选项未选中)": " §7- [选项文本]",
            "菜单主界面选项格式(选项被选中)": " §f- [选项文本]",
            "自定义主菜单内容": [
                {
                    "显示名": "示例功能:自尽",
                    "执行的指令": [
                        "/kill @a[name=[玩家名]]",
                        "/title @a[name=[玩家名]] title §c已自尽",
                    ],
                },
                {
                    "显示名": "示例功能:设置重生点",
                    "执行的指令": [
                        "/execute as @a[name=[玩家名]] run spawnpoint",
                        "/title @a[name=[玩家名]] title §a已设置重生点",
                    ],
                },
            ],
        }
        self.cfg, _ = cfg.get_plugin_config_and_version(
            self.name, CFG_STD, CFG_DEFAULT, (0, 0, 1)
        )
        menu_patterns[:] = (
            self.cfg["单页最大选项数"],
            self.cfg["菜单主界面格式头"],
            self.cfg["菜单主界面选项格式(选项未选中)"],
            self.cfg["菜单主界面选项格式(选项被选中)"],
            self.cfg["菜单主界面格式尾"],
        )
        for menu_arg in self.cfg["自定义主菜单内容"]:
            self.register_main_page(self.create_menu_cb(menu_arg), menu_arg["显示名"])

    def create_menu_cb(self, menu_arg):
        def menu_cb(player: str):
            for cmd in menu_arg["执行的指令"]:
                self.game_ctrl.sendwocmd(utils.simple_fmt({"[玩家名]": player}, cmd))
            return False

        return menu_cb

    @utils.thread_func("放置雪球菜单命令块")
    def place_cbs(self, player: Player, _):
        _, x, y, z = (int(i) for i in player.getPos())
        for cbtype, cond, cmd in SNOWBALL_CMDS:
            p = self.interact.make_packet_command_block_update(
                (x, y, z), cmd, mode=cbtype, conditional=bool(cond)
            )
            self.interact.place_command_block(p, 5)
            x += 1
        player.show("雪球菜单命令方块初始化完成")

    @utils.thread_func("雪球菜单打开或切页")
    def next_page(self, player: str):
        self.game_ctrl.sendwocmd(f"/tag @a[name={player}] add snowmenu")
        self.game_ctrl.sendwocmd(
            f'/replaceitem entity @a[name={player},m=!1] slot.weapon.mainhand 0 keep snowball 1 0 {{"item_lock":{{"mode":"lock_in_inventory"}}}}'
        )
        now_page = self.in_snowball_menu.get(player)
        if now_page is None:
            self.game_ctrl.sendwocmd(
                f"/execute as @a[name={player}] at @s run tp ~~~~ 0"
            )
            self.in_snowball_menu[player] = self.reg_pages["default"]
            self.multi_snowball_page[player] = 0
            self.show_page_thread(player)
        elif isinstance(now_page, Page):
            next_page = now_page.next_page_id
            self.in_snowball_menu[player] = self.reg_pages[next_page]
        elif isinstance(now_page, MultiPage):
            if now_page.page_id == "default":
                self.multi_snowball_page[player] += 1
                if self.multi_snowball_page[player] >= len(main_page_menus):
                    self.multi_snowball_page[player] = 0
            else:
                self.multi_snowball_page[player] += 1
                r = now_page.page_cb(player, self.multi_snowball_page[player])
                if r is None:
                    self.multi_snowball_page[player] = 0
                    r = now_page.page_cb(player, 0)
                    self.game_ctrl.player_actionbar(player, r)  # type: ignore
        self.show_page(player)

    @utils.thread_func("展示雪球菜单页")
    def show_page_thread(self, player: str):
        if player not in self.in_snowball_menu.keys():
            fmts.print_war(f"{player} 的菜单显示不正常: 可能是立刻退出了！")
        while player in self.in_snowball_menu.keys():
            self.show_page(player)
            time.sleep(1)

    def show_page(self, player: str):
        mp = self.in_snowball_menu[player]
        if isinstance(mp, Page):
            page_text = mp.page_texts
        else:
            try:
                page_text = mp.page_cb(player, self.multi_snowball_page[player])
            except Exception:
                fmts.print_err("§4雪球菜单页面显示 出现问题:")
                fmts.print_err(traceback.format_exc())
                return
        if page_text is None:
            return
        self.game_ctrl.player_actionbar(player, page_text)

    @utils.thread_func("雪球菜单执行")
    def menu_confirm(self, player: str):
        self._dbg(f"{player} confirmed")
        # 确认选项
        if player not in self.in_snowball_menu.keys():
            fmts.print_war(f"玩家: {player} 雪球菜单确认异常: 不在雪球菜单页内")
            return
        page = self.in_snowball_menu[player]
        if isinstance(page, Page):
            res = page.ok_cb(player)
        else:
            res = page.ok_cb(player, self.multi_snowball_page[player])
        if res is None:
            self.remove_player_in_menu(player)
        else:
            self.game_ctrl.sendwocmd(
                f"/execute as @a[name={player}] at @s run tp ~~~~ 0"
            )
            if res is True:
                # 保留在本页
                pass
            elif res is False:
                # 不应该被执行
                raise ValueError("菜单项不可返回 False")
            elif isinstance(res, Page | MultiPage):
                # 跳转到另一个页面
                self.set_player_page(player, res, 0)
            elif isinstance(res, tuple):
                # 跳转到另一个页面 并指定在第几页
                self.set_player_page(player, res[0], res[1])
            else:
                raise ValueError(f"返回不可以是 {res}")

    def menu_escape(self, player: str):
        if player not in self.in_snowball_menu.keys():
            fmts.print_war(f"玩家: {player} 雪球菜单退出异常: 不在雪球菜单页内")
            self.game_ctrl.sendwocmd(f"/tag @a[name={player}] remove snowmenu")
            return
        cb = self.in_snowball_menu[player].exit_cb
        _parent = self.in_snowball_menu[player].parent_page_id
        if _parent is None:
            self.game_ctrl.player_actionbar(player, self.cfg["菜单退出提示"])
            self.remove_player_in_menu(player)
        else:
            self.in_snowball_menu[player] = self.reg_pages[_parent]
            self.multi_snowball_page[player] = 0
        self.game_ctrl.sendwocmd(f"execute as {player} at @s run tp ~~~ ~ 0")
        if cb is not None:
            cb(player)

    def remove_player_in_menu(self, player: str):
        self._dbg(f"{player} exit menu")
        del self.in_snowball_menu[player]
        if player in self.multi_snowball_page.keys():
            del self.multi_snowball_page[player]
        self.game_ctrl.sendwocmd(f"/tag @a[name={player}] remove snowmenu")

    def _dbg(self, dbgdata: str):
        if DBG_MODE:
            self.game_ctrl.say_to("@a", f"§7<雪球菜单> {dbgdata}")


SNOWBALL_CMDS: list[tuple[int, int, str]] = [
    (
        1,
        0,
        '/execute as @e[type=snowball] at @s run execute as @p[r=3] run tellraw @a[tag=robot] {"rawtext":[{"text":"snowball.menu.use"},{"selector":"@s"}]}',
    ),
    (2, 1, "kill @e[type=snowball]"),
    (
        2,
        0,
        '/execute as @a[rxm=88,tag=snowmenu,tag=!snowmenu:escape] run tellraw @a[tag=robot] {"rawtext":[{"text":"snowball.menu.escape"},{"selector":"@s"}]}',
    ),
    (2, 1, "/tag @a[rxm=88,tag=!snowmenu:escape] add snowmenu:escape"),
    (2, 0, "/tag @a[rx=87,tag=snowmenu:escape] remove snowmenu:escape"),
    (
        2,
        0,
        '/execute as @a[rx=-88,tag=snowmenu,tag=!snowmenu:confirm] run tellraw @a[tag=robot] {"rawtext":[{"text":"snowball.menu.confirm"},{"selector":"@s"}]}',
    ),
    (2, 1, "/tag @a[rx=-88,tag=snowmenu,tag=!snowmenu:confirm] add snowmenu:confirm"),
    (2, 0, "/tag @a[rxm=-87,tag=snowmenu:confirm] remove snowmenu:confirm"),
]
entry = plugin_entry(SnowMenu, "雪球菜单v2")

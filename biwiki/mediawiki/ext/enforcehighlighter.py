# Written by a3ref contributors on 2026-10-30 after the HTML of the BI wiki's Enforce Script Highlighter extension
# (https://community.bistudio.com/, not published), whose output it reproduces.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The <enforce> tag of the BI wiki: Enforce Script (Arma Reforger, DayZ) code with highlighted tokens.

The extension's source is not public; the rules here were inferred from the wiki's action=parse output:

- the content is trimmed (PHP trim()); empty content gives "-no code provided-" without a game class;
- ``game="dayz"`` gives the class ``dayz`` and no links; any other value (or none) gives ``armar``, whose known
  script types link to the Enfusion script editor (``enfusion://ScriptEditor/scripts/<file>;<line>``);
- ``inline`` gives a ``<span>`` without the scroller ``<div>``;
- tokens are classed like Pygments: ``k`` keyword, ``nt`` primitive type, ``nc`` class name, ``c`` ALL_CAPS
  constant, ``mv`` member variable (``m_*``, ``s_*``), ``om`` method call (a name directly followed by ``(``),
  ``s`` string, ``c1``/``cm`` line/block comment, ``cp`` preprocessor directive, ``o`` operator, ``p``
  punctuation; numbers, ``'...'``, ``|``, ``^``, ``%``, ``?`` and other names stay plain;
- names: ``class X`` / ``enum X`` make X a class name in the whole snippet; a known type stays a class name
  when called, but keeps its link only inside ``[...]`` (attributes); after ``new`` a name is never a method
  call; a capitalised name (two letters at least) after ``.`` stays plain;
- strings are escaped with ENT_QUOTES, comments without (their quotes stay as they are);
- the HTML goes into a nowiki strip marker (see ``enforce_hook``).

Parser interface: set_hook.
"""
from __future__ import annotations

import re
from typing import Optional

NO_CODE = "-no code provided-"

GAMES = ("armar", "dayz")
DEFAULT_GAME = "armar"

LINK_PREFIX = "enfusion://ScriptEditor/scripts/"

KEYWORDS = frozenset("""
    if else switch case default break continue return while for foreach new delete
    class enum extends typedef modded sealed
    static const protected private override proto native external event owned out inout notnull volatile thread
    reference ref autoptr auto
    null this super true false
""".split())

# Built-in types, classed whatever the game: (class, script location in Arma Reforger or None).
BUILTIN_TYPES: dict[str, tuple[str, Optional[str]]] = {
    "int": ("nt", "Core/generated/Types/int.c;12"),
    "float": ("nt", "Core/generated/Types/float.c;12"),
    "bool": ("nt", "Core/generated/Types/bool.c;12"),
    "typename": ("nt", "Core/generated/Types/typename.c;12"),
    "func": ("nt", "Core/proto/Types.c;143"),
    "void": ("nt", None),
    "string": ("nc", "Core/generated/Types/string.c;12"),
    "vector": ("nc", "Core/generated/Types/vector.c;12"),
    "array": ("nc", "Core/proto/Types.c;154"),
    "set": ("nc", "Core/proto/Types.c;396"),
    "map": ("nc", "Core/proto/Types.c;485"),
}

# Arma Reforger script classes the wiki links (as seen in its output); other class names get no link.
ARMAR_TYPES: dict[str, str] = {
    "AIAgent": "Game/generated/AI/AIAgent.c;16",
    "AIGroup": "Game/generated/AI/AIGroup.c;16",
    "AIWaypoint": "Game/generated/AI/AIWaypoint.c;20",
    "ArmaReforgerScripted": "Game/game.c;31",
    "Attribute": "Core/generated/Attributes/Attribute.c;12",
    "BaseContainer": "Core/generated/Containers/BaseContainer.c;12",
    "BaseContainerTools": "Core/generated/Containers/BaseContainerTools.c;12",
    "BaseGameMode": "Game/generated/GameMode/BaseGameMode.c;16",
    "BaseRplComponent": "GameLib/generated/Components/BaseRplComponent.c;72",
    "BaseSerializationSaveContext": "Game/Plugins/Serialization/BackwardsCompatiblity.c;6",
    "BaseWorld": "Core/generated/World/BaseWorld.c;12",
    "ButtonWidget": "Core/generated/UI/ButtonWidget.c;15",
    "CameraBase": "Game/generated/Camera/CameraBase.c;16",
    "ChimeraCharacter": "Game/generated/Character/ChimeraCharacter.c;12",
    "ChimeraMenuBase": "Game/UI/Menu/ChimeraMenuBase.c;71",
    "Class": "Core/proto/Types.c;34",
    "Color": "Core/generated/Visual/Color.c;12",
    "ContainerSerializationSaveContext": "Game/Plugins/Serialization/BackwardsCompatiblity.c;14",
    "DamageManagerComponent": "Game/generated/Components/DamageManagerComponent.c;12",
    "Debug": "Core/generated/Debug/Debug.c;12",
    "EDamageType": "Game/generated/HitZone/EDamageType.c;12",
    "EQueryEntitiesFlags": "Core/generated/World/EQueryEntitiesFlags.c;12",
    "EntityEvent": "Core/generated/Entities/EntityEvent.c;13",
    "EntityID": "Core/proto/EnEntity.c;6",
    "EntityPrefabData": "Core/generated/Entities/EntityPrefabData.c;18",
    "EntitySpawnParams": "GameLib/gameLib.c;123",
    "Faction": "Game/generated/Faction/Faction.c;12",
    "FactionManager": "Game/generated/Faction/FactionManager.c;16",
    "FileHandle": "Core/generated/System/FileHandle.c;68",
    "FileIO": "Core/generated/System/FileIO.c;12",
    "Game": "GameLib/generated/Game.c;7",
    "GameEntity": "Game/generated/Entities/GameEntity.c;16",
    "GenericComponent": "GameLib/generated/Components/GenericComponent.c;12",
    "GenericEntity": "GameLib/generated/Entities/GenericEntity.c;15",
    "IEntity": "Core/generated/Entities/IEntity.c;12",
    "IEntityComponentSource": "Core/generated/Containers/IEntityComponentSource.c;12",
    "IEntitySource": "Core/generated/Containers/IEntitySource.c;12",
    "ImageWidget": "Core/generated/UI/ImageWidget.c;12",
    "InputManager": "GameLib/generated/Input/InputManager.c;19",
    "InventoryItemComponent": "Game/generated/Components/InventorySystem/InventoryItemComponent.c;12",
    "JsonApiStruct": "GameLib/generated/online/JsonApiStruct.c;15",
    "Managed": "Core/proto/Types.c;112",
    "Math": "Core/generated/Math/Math.c;12",
    "Math3D": "Core/generated/Math/Math3D.c;12",
    "MenuBase": "GameLib/generated/Menu/MenuBase.c;31",
    "Physics": "Core/generated/Physics/Physics.c;21",
    "PlayerController": "Game/generated/Player/PlayerController.c;16",
    "Resource": "Core/generated/Resources/Resource.c;24",
    "ResourceName": "Core/generated/Types/ResourceName.c;12",
    "RestApi": "GameLib/generated/online/RestApi.c;12",
    "RestCallback": "GameLib/generated/online/RestCallback.c;71",
    "RplComponent": "Game/generated/Components/RplComponent.c;17",
    "RplId": "Core/generated/Replication/RplId.c;13",
    "SCR_AIGroup": "Game/Entities/SCR_AIGroup.c;67",
    "SCR_BaseGameMode": "Game/GameMode/SCR_BaseGameMode.c;138",
    "SCR_BaseTriggerEntity": "Game/Entities/Triggers/SCR_BaseTriggerEntity.c;7",
    "SCR_ButtonComponent": "Game/UI/Components/WidgetLibrary/SCR_ButtonComponent.c;4",
    "SCR_CharacterDamageManagerComponent": "Game/Components/Damage/SCR_CharacterDamageManagerComponent.c;18",
    "SCR_ChimeraCharacter": "GameCode/Character/SCR_ChimeraCharacter.c;33",
    "SCR_EditableEntityComponent": "Game/Editor/Components/EditableEntity/SCR_EditableEntityComponent.c;13",
    "SCR_Enum": "Game/Global/SCR_Enum.c;1",
    "SCR_Faction": "Game/Faction/SCR_Faction.c;5",
    "SCR_FactionManager": "Game/GameMode/FactionManager/SCR_FactionManager.c;10",
    "SCR_HUDManagerComponent": "Game/UI/HUD/SCR_HUDManagerComponent.c;23",
    "SCR_InventoryStorageManagerComponent": "Game/Inventory/SCR_InventoryStorageManagerComponent.c;460",
    "SCR_JsonSaveContext": "Game/Plugins/Serialization/BackwardsCompatiblity.c;29",
    "SCR_PlayerController": "Game/Player/SCR_PlayerController.c;30",
    "ScriptAndConfig": "Core/proto/Types.c;123",
    "ScriptBitReader": "Core/proto/EnNetwork.c;198",
    "ScriptBitWriter": "Core/proto/EnNetwork.c;126",
    "ScriptCallQueue": "GameLib/tools.c;52",
    "ScriptComponent": "GameLib/generated/Components/ScriptComponent.c;23",
    "ScriptCtx": "Core/proto/EnNetwork.c;35",
    "ScriptEditor": "GameLib/generated/WorkbenchAPI/Modules/ScriptEditor.c;14",
    "ScriptInvoker": "GameLib/tools.c;134",
    "ScriptInvokerBase": "GameLib/tools.c;117",
    "ScriptInvokerVoid": "Game/Helpers/SCR_ScriptInvokerHelper.c;9",
    "ScriptedWidgetComponent": "Core/generated/UI/ScriptedWidgetComponent.c;12",
    "Shape": "Core/generated/Debug/Shape.c;13",
    "ShapeFlags": "Core/generated/Debug/ShapeFlags.c;12",
    "SoundComponent": "Game/generated/Components/SoundComponent.c;12",
    "System": "Core/generated/System/System.c;12",
    "TBoolArray": "Core/proto/Types.c;388",
    "TFloatArray": "Core/proto/Types.c;386",
    "TIntArray": "Core/proto/Types.c;387",
    "TResourceNameArray": "Core/proto/Types.c;394",
    "TStringArray": "Core/proto/Types.c;385",
    "TVectorArray": "Core/proto/Types.c;392",
    "TextWidget": "Core/generated/UI/TextWidget.c;15",
    "TraceParam": "Core/generated/World/TraceParam.c;15",
    "Tuple2": "Core/tuple.c;60",
    "UIInfo": "Game/generated/UI/UIInfo.c;13",
    "UIWidgets": "Core/attributes.c;39",
    "Vehicle": "GameCode/Vehicle/Vehicle.c;22",
    "Widget": "Core/generated/UI/Widget.c;12",
    "WidgetManager": "Core/generated/UI/WidgetManager.c;15",
    "Workbench": "GameLib/generated/WorkbenchAPI/Workbench.c;14",
    "WorkspaceWidget": "Core/generated/UI/WorkspaceWidget.c;15",
    "World": "GameLib/generated/World/World.c;15",
    "WorldEditor": "GameLib/generated/WorkbenchAPI/Modules/WorldEditor.c;14",
    "WorldEditorAPI": "Core/generated/WorkbenchAPI/WorldEditorAPI.c;12",
    "WorldTimestamp": "Core/generated/World/WorldTimestamp.c;25",
}

# One token per match, tried in this order at each position (so "x=//c" is "x", "=//", "c": an operator run
# swallows a following "//", as on the wiki).
_TOKEN = re.compile(r"""
    (?P<c1>//[^\n]*)
  | (?P<cm>/\*.*?(?:\*/|\Z))
  | (?P<s>"(?:.*?(?<!\\)"|.*))
  | (?P<cp>(?<!\w)\#[A-Za-z_]\w*)
  | (?P<name>[A-Za-z_]\w*)
  | (?P<number>\d\w*)
  | (?P<o>[=!<>+\-*/&~]+)
  | (?P<p>[(){}\[\];:.,])
  | (?P<other>[^/"\#A-Za-z_\d=!<>+\-*&~(){}\[\];:.,]+|.)
""", re.S | re.X)

_CONSTANT = re.compile(r"[A-Z][A-Z_]+")
_MEMBER = re.compile(r"[ms]_\w*")
_CLASS_NAME = re.compile(r"[A-Z][A-Za-z]\w*")
_TRIM = " \t\n\r\0\x0b"


def _escape(text: str) -> str:
    """PHP htmlspecialchars() with ENT_QUOTES, with "&#39;" as the wiki's output has it."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


def _escape_comment(text: str) -> str:
    """Comment text as the wiki gives it: htmlspecialchars() without ENT_QUOTES.

    (Tag-like text such as <b> in a comment comes out differently on the wiki, as if the comment went through an
    HTML parser: "<b>x</b>" becomes '<span class="b">x</span>', "</b>" disappears, "<i>" stays. Not reproduced.)"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _span(cls: str, html: str) -> str:
    return f'<span class="{cls}">{html}</span>'


def _type_span(cls: str, name: str, location: Optional[str]) -> str:
    if location is None:
        return _span(cls, name)
    return _span(cls, f'<a href="{LINK_PREFIX}{location}">{name}</a>')


def highlight(code: str, game: str = DEFAULT_GAME) -> str:
    """The highlighted HTML of trimmed, non-empty Enforce Script code."""
    tokens = [(m.lastgroup, m.group(), m.start(), m.end()) for m in _TOKEN.finditer(code)]
    # names declared by "class X" / "enum X" are class names everywhere in the snippet, before and after
    declared = set()
    previous = None
    for kind, text, _, _ in tokens:
        if kind == "other" and text.isspace():
            continue
        if kind == "name" and previous in ("class", "enum"):
            declared.add(text)
        previous = text if kind == "name" else None
    links = game == "armar"
    out = []
    previous = None  # the previous token that is not whitespace
    brackets = 0  # depth of [...], where attributes such as [Attribute()] are written
    for kind, text, start, end in tokens:
        if kind == "name":
            out.append(_name(code, text, start, end, declared, links, previous == "new", brackets > 0))
        elif kind in ("c1", "cm"):
            out.append(_span(kind, _escape_comment(text)))
        elif kind in ("s", "cp", "o", "p"):
            out.append(_span(kind, _escape(text)))
            if text == "[":
                brackets += 1
            elif text == "]" and brackets:
                brackets -= 1
        else:
            out.append(_escape(text))
        if not (kind == "other" and text.isspace()):
            previous = text
    return "".join(out)


def _name(code: str, name: str, start: int, end: int, declared: set, links: bool, after_new: bool,
          in_brackets: bool) -> str:
    """The HTML of the name code[start:end]."""
    call = code.startswith("(", end)
    if name in KEYWORDS:
        return _span("k", name)
    # a known type is a class name even when called (Color(1), vector(1), new Color()), but only in an attribute
    # ([Attribute()]) does such a call keep its link
    if name in BUILTIN_TYPES:
        cls, location = BUILTIN_TYPES[name]
        return _type_span(cls, name, location if links and (in_brackets or not call) else None)
    if links and name in ARMAR_TYPES:
        return _type_span("nc", name, ARMAR_TYPES[name] if in_brackets or not call else None)
    if name in declared:
        return _span("nc", name)
    # after "new" a name is a class, never a method call
    if call and not after_new:
        return _span("om", name)
    if _CONSTANT.fullmatch(name):
        return _span("c", name)
    if _MEMBER.fullmatch(name):
        return _span("mv", name)
    # a capitalised name after "." is a member (Foo.Bar), not a class
    if _CLASS_NAME.fullmatch(name) and not (start and code[start - 1] == "."):
        return _span("nc", name)
    return name


def render(code: Optional[str], argv: dict) -> str:
    """The HTML of an <enforce> tag with content ``code`` and attributes ``argv``."""
    inline = "inline" in argv
    tag = "span" if inline else "div"
    code = (code or "").strip(_TRIM)
    if not code:
        return f'<{tag} class="enforcescripthighlighter-block">{NO_CODE}</{tag}>'
    game = (argv.get("game") or "").strip().lower()
    if game not in GAMES:
        game = DEFAULT_GAME
    html = highlight(code, game)
    if inline:
        return f'<span class="enforcescripthighlighter-block {game}">{html}</span>'
    return (f'<div class="enforcescripthighlighter-block {game}">'
            f'<div class="enforcescripthighlighter-scroller">{html}</div></div>')


def enforce_hook(text: Optional[str], argv: dict, parser, frame) -> dict:
    """Parser hook for the <enforce> tag.

    The HTML goes into a nowiki strip marker (like SyntaxHighlight's), so doBlockLevels sees only the marker: the
    block ends up in a paragraph that tidy splits into the wiki's <p class="mw-empty-elt"></p> pair, and the
    lines of the code get no <p> of their own."""
    return {0: render(text, argv), "markerType": "nowiki"}


def register(parser) -> None:
    """ParserFirstCallInit: the <enforce> tag."""
    parser.set_hook("enforce", enforce_hook)

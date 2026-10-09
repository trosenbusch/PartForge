"""Shared German wording of the Altium area: settings locations and component names.

One spelling everywhere (review finding F9): the program that writes SchLib/PcbLib files is the
**Bibliotheks-Writer** in every user text (the executable name ``altium-designer-mcp.exe`` only in
help texts), settings locations are written with ``›`` exactly as the UI shows them. The frontend
deep links of these places: ``/einstellungen#altium`` and ``/einstellungen/hausstil?ansicht=lagen``.
"""
from __future__ import annotations

from typing import Final

__all__ = [
    "SETTINGS_ALTIUM",
    "SETTINGS_ALTIUM_LINK",
    "SETTINGS_LAYERS",
    "SETTINGS_LAYERS_LINK",
    "SETTINGS_WRITER",
    "WRITER",
]

#: Name of the library writer in user texts.
WRITER: Final = "Bibliotheks-Writer"
#: Card with the X2.EXE path, the writer path, the backend and the automatic refresh.
SETTINGS_ALTIUM: Final = "Einstellungen › Allgemein › Altium Designer"
SETTINGS_ALTIUM_LINK: Final = "/einstellungen#altium"
#: The writer path field inside that card.
SETTINGS_WRITER: Final = f"{SETTINGS_ALTIUM} › {WRITER}"
#: Layer map and layer stack of the house style.
SETTINGS_LAYERS: Final = "Einstellungen › Hausstil › Lagen"
SETTINGS_LAYERS_LINK: Final = "/einstellungen/hausstil?ansicht=lagen"

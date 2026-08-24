"""
Capti Screens-Paket.

Jeder Screen ist ein eigenes CTkFrame und wird zentral über den
AppController verwaltet. Navigation läuft ausschließlich über den
Controller – Screens navigieren nie direkt untereinander.
"""

from ui.screens.base import Screen

__all__ = ["Screen"]
#!/usr/bin/env python3
"""
Playaway Audiobook Flasher - Calibre Interface Action Plugin
Allows flashing audiobooks directly from the Calibre library to Playaway hardware.
"""

try:
    from calibre.customize import InterfaceActionBase
except ImportError:
    class InterfaceActionBase:
        pass


class PlayawayFlasherPlugin(InterfaceActionBase):
    name                    = 'Playaway Audiobook Flasher'
    description             = 'Convert, chapterize, and flash audiobooks directly from your Calibre library to Playaway USB players.'
    supported_platforms     = ['windows', 'osx', 'linux']
    author                  = 'homealone944'
    version                 = (1, 0, 0)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.playaway_flasher.action:PlayawayAction'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.playaway_flasher.dialog import PlayawayConfigWidget
        return PlayawayConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()

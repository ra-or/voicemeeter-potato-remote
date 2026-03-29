Put your own Voicemeeter script presets in this folder.

Each line should be a Voicemeeter command, for example:
Strip[5].A1=1
Strip[5].A2=0
Bus[0].EQ.on=1

You can reference config.json values with placeholders:
{{main_route_strip_index}}
{{eq_bus_index}}

Then point to the file from presets.json:
"my_preset": {
  "label": "My preset",
  "script_file": "preset_scripts/my_preset.txt"
}

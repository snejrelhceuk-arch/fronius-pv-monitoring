"""Pi4-Tech WP-Hardware-Bridge (Rolle: HW-Bridge, keine eigene Engine).

Stellt die WP-Modbus-Schnittstelle (RS485/tty) als abgesicherten HTTP-Dienst
für den entfernten Primary bereit. Nur WP-Status lesen und Whitelist-Register
schreiben — keine Entscheidungslogik.
"""

"""Modulo Smart Home: scopre e interroga i dispositivi Xiaomi, Aqara e Tapo dell'operatore.

Ogni ecosistema usa un canale e un'autenticazione diversi:

- Xiaomi su WiFi: protocollo miIO (UDP 54321), serve il token del dispositivo.
- Xiaomi/Aqara su Bluetooth LE: annunci MiBeacon, spesso cifrati con una chiave
  legata all'account.
- Aqara Zigbee: raggiungibile solo tramite l'hub o una chiavetta Zigbee USB.
- Tapo (TP-Link): protocollo locale KLAP, servono le credenziali dell'account TP-Link.

Senza token o credenziali il modulo scopre e identifica, non controlla. Le
operazioni sono in sola lettura; i comandi che cambiano lo stato del dispositivo
passano da `CommandGuard` e richiedono la conferma esplicita dell'operatore.
"""

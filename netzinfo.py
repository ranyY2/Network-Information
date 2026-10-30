import ipaddress
import json
import re
import socket
import subprocess
import sys
from pathlib import Path


POWERSHELL_QUERY = r"""
$ErrorActionPreference = 'Stop'
$configs = @(
    Get-NetIPConfiguration |
        Where-Object {
            $_.NetAdapter.Status -eq 'Up' -and
            ($_.IPv4Address -or $_.IPv6Address -or $_.IPv4DefaultGateway -or $_.IPv6DefaultGateway)
        }
)
$profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
$result = @(
    foreach ($config in $configs) {
        $adapter = $config.NetAdapter
        $profile = $profiles | Where-Object { $_.InterfaceIndex -eq $adapter.ifIndex } | Select-Object -First 1
        [PSCustomObject]@{
            Name = $adapter.Name
            Description = $adapter.InterfaceDescription
            Status = [string]$adapter.Status
            MediaType = [string]$adapter.MediaType
            MacAddress = $adapter.MacAddress
            LinkSpeed = [string]$adapter.LinkSpeed
            InterfaceIndex = $adapter.ifIndex
            Mtu = $config.NetIPv4Interface.NlMtu
            DhcpIPv4 = [string]$config.NetIPv4Interface.Dhcp
            DhcpIPv6 = [string]$config.NetIPv6Interface.Dhcp
            DhcpServers = @($config.DhcpServer | Where-Object { $_ })
            DnsSuffix = $config.DNSSuffix
            ProfileName = $profile.Name
            NetworkCategory = [string]$profile.NetworkCategory
            IPv4 = @($config.IPv4Address | ForEach-Object { $_.IPAddress })
            IPv6 = @($config.IPv6Address | ForEach-Object { $_.IPAddress })
            Gateways = @(
                $config.IPv4DefaultGateway | ForEach-Object { $_.NextHop }
                $config.IPv6DefaultGateway | ForEach-Object { $_.NextHop }
            )
            DnsServers = @($config.DNSServer.ServerAddresses)
        }
    }
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
ConvertTo-Json -InputObject @($result) -Depth 5 -Compress
"""

ARP_ENTRY = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F-]{17})\s+(\w+)\s*$"
)

ASCII_LOGO = r"""
                       .
                      .  !\  _
                      l\/ ( /(_
                     _ `--" _/ .
                     \~")   (_,/)
                     _)/.   ,\,/
            _____,-"~    \ /   "~"-._____
        ,-~"     "~-.  .  "  .  ,-~"     "~-.
      ,^             ^. `. .' ,^             ^.
     /                 \  ^  /                 \
    Y___________________Y   Y___________________Y
    | |^~"|^   _ ^|"~^| |   | |"~"|^ _   ^|"~"| |
    | !   l   (_) !   ! l   | !   l (_)   !   ! |
    l  \  `\.___,/'  /  !   l  \  `\.___,/'  /  !
     \  ^.         ,^  /!   !\  ^.         ,^  /
      ^.  ~-------~  ,^\`v-v'/^.  ~-------~  ,^
      _)~-._______,-~   }---{   ~-._______,-~(_
 .--"~           ,-^7' /     \ `Y^-,           ~"--.
/               (_,/ ,/'     `\. \._)    ___        \
\_____.,--"~~~"--..,__        ___,..--<"~   ~"-.,___/
    / (    __,--~ _.._""~~~~"" ,-"  "-.`\     /~.-"
    `._"--~_,.--"~    \       /        \ `---' /
       "~""            \     /          "-.__,/
                       `L   ]'
                        l   !
                        j___L
                       (_____)
                        |   |
                        |   |

 _ ______       _______
| (_____ \    (_______)  _     _              | |
| |_____) )    _______ _| |_ _| |_ _____  ____| |  _
| |  ____/    |  ___  (_   _|_   _|____ |/ ___) |_/ )
| | |         | |   | | | |_  | |_/ ___ ( (___|  _ (
|_|_|         |_|   |_| \__)  \__)_____|\____)_| \_\
"""


def run_command(arguments, *, encoding=None):
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="replace",
            check=False,
        )
    except OSError as error:
        raise RuntimeError(f"Befehl konnte nicht gestartet werden: {arguments[0]} ({error})") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"{arguments[0]} wurde mit Fehler beendet.")
    return result.stdout


def get_connections():
    output = run_command(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            POWERSHELL_QUERY,
        ],
        encoding="utf-8",
    )
    try:
        data = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError("Die Netzwerkinformationen konnten nicht verarbeitet werden.") from error

    if not isinstance(data, list):
        raise RuntimeError("Unerwartetes Format der Netzwerkinformationen.")
    return data


def get_wifi_names():
    output = run_command(["netsh.exe", "wlan", "show", "interfaces"])
    names = []
    for line in output.splitlines():
        match = re.match(r"^\s*SSID\s*:\s*(.+?)\s*$", line)
        if match and match.group(1) != "BSSID" and match.group(1) not in names:
            names.append(match.group(1))
    return names


def get_router_names(gateways):
    router_names = []
    for gateway in gateways or []:
        try:
            hostname = socket.gethostbyaddr(gateway)[0].rstrip(".")
            router_name = f"{hostname} ({gateway})"
        except (OSError, socket.herror, socket.gaierror):
            router_name = f"{gateway} (Routername nicht aufloesbar)"
        if router_name not in router_names:
            router_names.append(router_name)
    return router_names


def display_network_info():
    connections = get_connections()
    if not connections:
        print("Keine aktive Netzwerkverbindung gefunden.")
        return

    try:
        wifi_names = get_wifi_names()
    except RuntimeError as error:
        wifi_names = []
        print(f"WARNUNG: WLAN-Name konnte nicht ermittelt werden: {error}")
    print("\nAktive Netzwerkverbindungen")
    print("=" * 28)
    print(f"WLAN-Name (SSID):       {', '.join(wifi_names) if wifi_names else 'Kein verbundenes WLAN gefunden'}")

    for connection in connections:
        router_names = get_router_names(connection.get("Gateways"))
        print(f"\n{connection.get('Name') or 'Netzwerkadapter'} ({connection.get('Description') or 'unbekannt'})")
        print(f"Router / Gateway:      {format_values(router_names)}")
        print(f"Internetprofil:        {connection.get('ProfileName') or 'Unbekannt'}")
        print(f"  Status:               {connection.get('Status') or 'Unbekannt'}")
        print(f"  Verbindungstyp:       {connection.get('MediaType') or 'Unbekannt'}")
        print(f"  MAC-Adresse:          {connection.get('MacAddress') or 'Unbekannt'}")
        print(f"  Verbindungsgeschw.:   {connection.get('LinkSpeed') or 'Unbekannt'}")
        print(f"  Schnittstellen-ID:    {connection.get('InterfaceIndex') or 'Unbekannt'}")
        print(f"  MTU (IPv4):           {connection.get('Mtu') or 'Unbekannt'}")
        print(f"  DHCP (IPv4):          {connection.get('DhcpIPv4') or 'Unbekannt'}")
        print(f"  DHCP (IPv6):          {connection.get('DhcpIPv6') or 'Unbekannt'}")
        print(f"  DHCP-Server:          {format_values(connection.get('DhcpServers'))}")
        print(f"  Netzwerkprofil:       {connection.get('ProfileName') or 'Unbekannt'}")
        print(f"  Netzwerk-Kategorie:   {connection.get('NetworkCategory') or 'Unbekannt'}")
        print(f"  DNS-Suffix:           {connection.get('DnsSuffix') or 'Keiner'}")
        print(f"  IPv4-Adresse(n):      {format_values(connection.get('IPv4'))}")
        print(f"  IPv6-Adresse(n):      {format_values(connection.get('IPv6'))}")
        print(f"  Standard-Gateway:     {format_values(connection.get('Gateways'))}")
        print(f"  DNS-Server:           {format_values(connection.get('DnsServers'))}")


def format_values(values):
    if not values:
        return "Keine"
    if isinstance(values, list):
        return ", ".join(str(value) for value in values if value) or "Keine"
    return str(values)


def display_arp_cache():
    devices = get_arp_devices()
    print("\nEintraege im lokalen ARP-Cache")
    print("(Das ist keine aktive Netzwerksuche.)")
    print(f"{'IP-Adresse':<18} {'MAC-Adresse':<20} {'Typ'}")
    print("-" * 48)
    if not devices:
        print("Keine Einträge gefunden.")
        return
    for ip_address, mac_address, entry_type in devices:
        print(f"{ip_address:<18} {mac_address:<20} {entry_type}")


def get_arp_devices():
    output = run_command(["arp.exe", "-a"])
    devices = []
    for line in output.splitlines():
        match = ARP_ENTRY.match(line)
        if not match:
            continue
        ip_address, mac_address, entry_type = match.groups()
        try:
            ipaddress.IPv4Address(ip_address)
        except ipaddress.AddressValueError:
            continue
        devices.append((ip_address, mac_address, entry_type))
    return devices


def launch_gui():
    try:
        import dearpygui.dearpygui as dpg
    except ImportError as error:
        raise RuntimeError(
            "Dear PyGui fehlt. Installiere die Abhaengigkeit mit: python -m pip install -r requirements.txt"
        ) from error

    def update_connections():
        dpg.delete_item("connection_cards", children_only=True)
        try:
            connections = get_connections()
        except RuntimeError as error:
            dpg.set_value("connection_status", f"Fehler beim Laden: {error}")
            return

        try:
            wifi_names = get_wifi_names()
            wifi_value = ", ".join(wifi_names) if wifi_names else "Kein WLAN verbunden"
            wifi_status = ""
        except RuntimeError as error:
            wifi_value = "Nicht verfuegbar"
            wifi_status = f"WLAN-Name konnte nicht ermittelt werden: {error}"

        dpg.set_value("wifi_value", wifi_value)
        if not connections:
            dpg.add_text(
                "Keine aktive Netzwerkverbindung gefunden.",
                parent="connection_cards",
                color=(175, 185, 198),
            )
        for connection in connections:
            title = connection.get("Name") or "Netzwerkadapter"
            description = connection.get("Description") or "unbekannt"
            router_names = get_router_names(connection.get("Gateways"))
            with dpg.child_window(
                parent="connection_cards",
                height=0,
                autosize_y=True,
                border=True,
            ):
                dpg.add_text(f"{title}  /  {description}", color=(245, 245, 245))
                dpg.add_separator()
                values = [
                    ("Status", connection.get("Status")),
                    ("Verbindungstyp", connection.get("MediaType")),
                    ("MAC-Adresse", connection.get("MacAddress")),
                    ("Geschwindigkeit", connection.get("LinkSpeed")),
                    ("Schnittstellen-ID", connection.get("InterfaceIndex")),
                    ("MTU IPv4", connection.get("Mtu")),
                    ("DHCP IPv4", connection.get("DhcpIPv4")),
                    ("DHCP IPv6", connection.get("DhcpIPv6")),
                    ("DHCP-Server", format_values(connection.get("DhcpServers"))),
                    ("Profil", connection.get("ProfileName")),
                    ("Netzwerkkategorie", connection.get("NetworkCategory")),
                    ("DNS-Suffix", connection.get("DnsSuffix")),
                    ("Router / Gateway", format_values(router_names)),
                    ("IPv4", format_values(connection.get("IPv4"))),
                    ("IPv6", format_values(connection.get("IPv6"))),
                    ("Gateway", format_values(connection.get("Gateways"))),
                    ("DNS-Server", format_values(connection.get("DnsServers"))),
                ]
                with dpg.table(
                    header_row=False,
                    policy=dpg.mvTable_SizingStretchProp,
                    borders_innerH=True,
                ):
                    dpg.add_table_column(init_width_or_weight=1)
                    dpg.add_table_column(init_width_or_weight=2)
                    for label, value in values:
                        with dpg.table_row():
                            dpg.add_text(label, color=(160, 173, 190))
                            dpg.add_text(str(value) if value else "Unbekannt", wrap=500)

        status = wifi_status or f"{len(connections)} aktive Verbindung(en) geladen."
        dpg.set_value("connection_status", status)

    arp_row_tags = []

    def update_arp_cache():
        for row_tag in arp_row_tags:
            dpg.delete_item(row_tag)
        arp_row_tags.clear()
        try:
            devices = get_arp_devices()
        except RuntimeError as error:
            dpg.set_value("arp_status", f"Fehler beim Lesen: {error}")
            return

        for index, (ip_address, mac_address, entry_type) in enumerate(devices):
            row_tag = f"arp_row_{index}"
            arp_row_tags.append(row_tag)
            with dpg.table_row(parent="arp_table", tag=row_tag):
                dpg.add_text(ip_address)
                dpg.add_text(mac_address)
                dpg.add_text(entry_type)
        dpg.set_value(
            "arp_status",
            f"{len(devices)} Eintraege im lokalen Cache (keine aktive Netzwerksuche).",
        )

    def refresh_all(sender, app_data, user_data):
        update_connections()
        update_arp_cache()

    dpg.create_context()
    logo_path = Path(__file__).resolve().with_name("anonymous_logo.png")
    if not logo_path.is_file():
        dpg.destroy_context()
        raise RuntimeError(f"Das Logo wurde nicht gefunden: {logo_path}")
    monospace_font_path = Path(r"C:\Windows\Fonts\consola.ttf")
    if not monospace_font_path.is_file():
        dpg.destroy_context()
        raise RuntimeError(f"Die Schriftart fuer das ASCII-Logo wurde nicht gefunden: {monospace_font_path}")
    try:
        logo_width, logo_height, _, logo_data = dpg.load_image(str(logo_path))
    except (OSError, RuntimeError, ValueError) as error:
        dpg.destroy_context()
        raise RuntimeError(f"Das Logo konnte nicht geladen werden: {error}") from error

    with dpg.texture_registry():
        dpg.add_static_texture(
            logo_width,
            logo_height,
            logo_data,
            tag="anonymous_logo_texture",
        )

    with dpg.font_registry():
        dpg.add_font(str(monospace_font_path), 12, tag="ascii_logo_font")

    with dpg.theme() as app_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (10, 10, 10), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (20, 20, 20), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (32, 32, 32), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Button, (43, 43, 43), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (68, 68, 68), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (88, 88, 88), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Header, (46, 46, 46), category=dpg.mvThemeCat_Core)
            dpg.add_theme_color(dpg.mvThemeCol_Text, (245, 245, 245), category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 8, category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 7, category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 5, category=dpg.mvThemeCat_Core)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 18, 16, category=dpg.mvThemeCat_Core)

    with dpg.window(tag="main_window", label="Netzwerk-Info", no_collapse=True):
        with dpg.group(horizontal=True):
            dpg.add_image("anonymous_logo_texture", width=64, height=64)
            with dpg.group():
                dpg.add_text("ANONYMOUS", color=(245, 245, 245))
                dpg.add_text("NETZWERK-INFO", color=(245, 245, 245))
                dpg.add_text("Lokale Verbindungsdetails", color=(165, 165, 165))

        dpg.add_spacer(height=12)
        dpg.add_button(
            label="Informationen aktualisieren",
            callback=refresh_all,
        )
        dpg.add_spacer(height=8)
        with dpg.tab_bar():
            with dpg.tab(label="Verbindung"):
                with dpg.group(horizontal=True):
                    dpg.add_text("WLAN (SSID):", color=(160, 173, 190))
                    dpg.add_text("Wird geladen...", tag="wifi_value")
                dpg.add_spacer(height=6)
                dpg.add_text("Adapter", color=(245, 245, 245))
                dpg.add_child_window(tag="connection_cards", height=390, border=False)
                dpg.add_text("Lade Verbindungsdaten...", tag="connection_status", color=(160, 173, 190))
            with dpg.tab(label="Lokale Geraete"):
                dpg.add_text("Eintraege aus dem lokalen ARP-Cache", color=(160, 173, 190))
                with dpg.table(
                    tag="arp_table",
                    header_row=True,
                    resizable=True,
                    policy=dpg.mvTable_SizingStretchProp,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                ):
                    dpg.add_table_column(label="IP-Adresse")
                    dpg.add_table_column(label="MAC-Adresse")
                    dpg.add_table_column(label="Typ")
                dpg.add_text("Lade Cache...", tag="arp_status", color=(160, 173, 190))
                dpg.add_text("Hinweis: Der ARP-Cache ist keine aktive Netzwerksuche.", color=(160, 173, 190))
            with dpg.tab(label="ASCII-Logo"):
                dpg.add_text("Monochrome Darstellung aus logo.sh", color=(165, 165, 165))
                with dpg.child_window(height=560, border=True):
                    dpg.add_text(ASCII_LOGO, tag="ascii_logo", wrap=0)
                    dpg.bind_item_font("ascii_logo", "ascii_logo_font")

    dpg.bind_theme(app_theme)
    dpg.create_viewport(
        title="Netzwerk-Info",
        small_icon=str(logo_path),
        large_icon=str(logo_path),
        width=780,
        height=720,
        resizable=False,
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    update_connections()
    update_arp_cache()
    dpg.start_dearpygui()
    dpg.destroy_context()


def main():
    if sys.platform != "win32":
        print("Dieses Skript ist für Windows ausgelegt.")
        return 1

    if "--cli" not in sys.argv[1:]:
        try:
            launch_gui()
        except RuntimeError as error:
            print(f"Fehler: {error}", file=sys.stderr)
            return 1
        return 0

    while True:
        print(
            "\nNetzwerk-Info"
            "\n============="
            "\n1. Verbindungsdetails anzeigen"
            "\n2. Lokalen ARP-Cache anzeigen"
            "\n3. Beides anzeigen"
            "\n0. Beenden"
        )
        choice = input("Auswahl: ").strip()
        try:
            if choice == "1":
                display_network_info()
            elif choice == "2":
                display_arp_cache()
            elif choice == "3":
                display_network_info()
                display_arp_cache()
            elif choice == "0":
                print("Auf Wiedersehen.")
                return 0
            else:
                print("Ungueltige Auswahl. Bitte 0, 1, 2 oder 3 eingeben.")
        except RuntimeError as error:
            print(f"Fehler: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

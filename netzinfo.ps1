$ErrorActionPreference = 'Stop'

try {
    $connections = @(
        Get-NetIPConfiguration |
            Where-Object {
                $_.NetAdapter.Status -eq 'Up' -and
                ($_.IPv4Address -or $_.IPv6Address -or $_.IPv4DefaultGateway -or $_.IPv6DefaultGateway)
            }
    )
}
catch {
    Write-Error "Netzwerkinformationen konnten nicht gelesen werden: $($_.Exception.Message)"
    exit 1
}

if ($connections.Count -eq 0) {
    Write-Output 'Keine aktive Netzwerkverbindung gefunden.'
    exit 0
}

Write-Output 'Aktive Netzwerkverbindungen'
Write-Output '============================'

$wlanDetails = @(& netsh.exe wlan show interfaces 2>$null)
$ssids = @(
    foreach ($line in $wlanDetails) {
        if ($line -match '^\s*SSID\s*:\s*(.+?)\s*$' -and $Matches[1] -ne 'BSSID') {
            $Matches[1]
        }
    }
)
$ssids = @($ssids | Where-Object { $_ } | Select-Object -Unique)

Write-Output "  WLAN-Name (SSID):   $(if ($ssids.Count) { $ssids -join ', ' } else { 'Kein verbundenes WLAN gefunden' })"

foreach ($connection in $connections) {
    $adapter = $connection.NetAdapter
    $profile = Get-NetConnectionProfile -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue
    $ipv4 = @($connection.IPv4Address | ForEach-Object { $_.IPAddress })
    $ipv6 = @($connection.IPv6Address | ForEach-Object { $_.IPAddress })
    $gateways = @(
        $connection.IPv4DefaultGateway | ForEach-Object { $_.NextHop }
        $connection.IPv6DefaultGateway | ForEach-Object { $_.NextHop }
    )
    $dnsServers = @($connection.DNSServer.ServerAddresses)
    $dhcpServers = @($connection.DhcpServer | Where-Object { $_ })
    $dnsSuffix = $connection.DNSSuffix
    $ipv4Dhcp = $connection.NetIPv4Interface.Dhcp
    $ipv6Dhcp = $connection.NetIPv6Interface.Dhcp
    $mtu = $connection.NetIPv4Interface.NlMtu
    $connectorPresent = if ($adapter.ConnectorPresent) { 'Ja' } else { 'Nein' }

    Write-Output ''
    Write-Output "$($adapter.Name) ($($adapter.InterfaceDescription))"
    Write-Output "  Status:             $($adapter.Status)"
    Write-Output "  Verbindungstyp:     $($adapter.MediaType)"
    Write-Output "  Physischer Anschluss: $connectorPresent"
    Write-Output "  MAC-Adresse:        $($adapter.MacAddress)"
    Write-Output "  Verbindungsgeschw.: $($adapter.LinkSpeed)"
    Write-Output "  Schnittstellen-ID:  $($adapter.ifIndex)"
    Write-Output "  MTU (IPv4):         $(if ($mtu) { $mtu } else { 'Unbekannt' })"
    Write-Output "  DHCP (IPv4):        $(if ($ipv4Dhcp) { $ipv4Dhcp } else { 'Unbekannt' })"
    Write-Output "  DHCP (IPv6):        $(if ($ipv6Dhcp) { $ipv6Dhcp } else { 'Unbekannt' })"
    Write-Output "  DHCP-Server:        $(if ($dhcpServers.Count) { $dhcpServers -join ', ' } else { 'Nicht verfuegbar' })"
    Write-Output "  DNS-Suffix:         $(if ($dnsSuffix) { $dnsSuffix } else { 'Keiner' })"

    if ($profile) {
        Write-Output "  Netzwerkprofil:     $($profile.Name)"
        Write-Output "  Netzwerk-Kategorie: $($profile.NetworkCategory)"
    }

    Write-Output "  IPv4-Adresse(n):    $(if ($ipv4.Count) { $ipv4 -join ', ' } else { 'Keine' })"
    Write-Output "  IPv6-Adresse(n):    $(if ($ipv6.Count) { $ipv6 -join ', ' } else { 'Keine' })"
    Write-Output "  Standard-Gateway:   $(if ($gateways.Count) { $gateways -join ', ' } else { 'Keines' })"
    Write-Output "  DNS-Server:         $(if ($dnsServers.Count) { $dnsServers -join ', ' } else { 'Keine' })"
}

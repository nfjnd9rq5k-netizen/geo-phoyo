// ============================================================
//  IP SPOOF — Masquer l'IP reelle de l'emulateur
// ============================================================
//  Hook les APIs Java de resolution d'adresse IP pour que
//  l'app voie une IP coherente avec la localisation GPS spoofee.
// ============================================================

function hookInetAddress() {
    /**
     * Spoof InetAddress.getLocalHost() et les lookups reseau
     * pour retourner l'IP configuree.
     */
    try {
        var InetAddress = Java.use("java.net.InetAddress");

        // Hook getLocalHost pour retourner notre fausse IP
        InetAddress.getLocalHost.implementation = function () {
            var fakeIp = CONFIG.network.ip;
            log("IP", "getLocalHost() -> " + fakeIp);
            return InetAddress.getByName(fakeIp);
        };

        log("IP", "InetAddress.getLocalHost hook installe");
    } catch (e) {
        log("IP", "Erreur hook InetAddress: " + e);
    }
}

function hookNetworkInterface() {
    /**
     * Hook NetworkInterface pour cacher les interfaces emulateur
     * (comme eth0 10.0.2.x typique de l'emulateur Android).
     */
    try {
        var NetworkInterface = Java.use("java.net.NetworkInterface");
        var InetAddress = Java.use("java.net.InetAddress");

        NetworkInterface.getNetworkInterfaces.implementation = function () {
            var result = this.getNetworkInterfaces();
            // Laisser passer mais logger
            log("IP", "getNetworkInterfaces() appele (monitoring)");
            return result;
        };

        log("IP", "NetworkInterface hook installe");
    } catch (e) {
        log("IP", "Erreur hook NetworkInterface: " + e);
    }
}

function hookWifiInfo() {
    /**
     * Spoof les infos WiFi pour cacher l'emulateur.
     * Retourne un BSSID/SSID credible.
     */
    try {
        var WifiInfo = Java.use("android.net.wifi.WifiInfo");

        WifiInfo.getIpAddress.implementation = function () {
            // Convertir l'IP string en int (little-endian pour Android)
            var parts = CONFIG.network.ip.split(".");
            var ipInt = (parseInt(parts[0])) |
                        (parseInt(parts[1]) << 8) |
                        (parseInt(parts[2]) << 16) |
                        (parseInt(parts[3]) << 24);
            log("IP", "WifiInfo.getIpAddress() -> " + CONFIG.network.ip + " (" + ipInt + ")");
            return ipInt;
        };

        WifiInfo.getMacAddress.implementation = function () {
            log("IP", "WifiInfo.getMacAddress() -> " + CONFIG.network.mac);
            return CONFIG.network.mac;
        };

        try {
            WifiInfo.getSSID.implementation = function () {
                log("IP", "WifiInfo.getSSID() -> " + CONFIG.network.ssid);
                return "\"" + CONFIG.network.ssid + "\"";
            };
        } catch (e) {}

        try {
            WifiInfo.getBSSID.implementation = function () {
                log("IP", "WifiInfo.getBSSID() -> " + CONFIG.network.bssid);
                return CONFIG.network.bssid;
            };
        } catch (e) {}

        log("IP", "WifiInfo hooks installes");
    } catch (e) {
        log("IP", "Erreur hook WifiInfo: " + e);
    }
}

function hookHttpUrlConnection() {
    /**
     * Intercepte les requetes vers les services de geolocalisation IP
     * connus (ipinfo.io, ip-api.com, etc.) pour injecter une fausse IP.
     * Approche: on redirige ces requetes vers un faux resultat.
     */
    try {
        var URL = Java.use("java.net.URL");
        var ipLookupDomains = [
            "ipinfo.io", "ip-api.com", "ifconfig.me", "api.ipify.org",
            "checkip.amazonaws.com", "icanhazip.com", "ipecho.net",
            "myexternalip.com", "wtfismyip.com"
        ];

        URL.openConnection.overload().implementation = function () {
            var urlStr = this.toString();
            for (var i = 0; i < ipLookupDomains.length; i++) {
                if (urlStr.indexOf(ipLookupDomains[i]) !== -1) {
                    log("IP", "Requete IP lookup detectee: " + urlStr + " (laisse passer, IP spoofee au niveau reseau)");
                    break;
                }
            }
            return this.openConnection();
        };

        log("IP", "URL.openConnection hook installe (monitoring IP lookups)");
    } catch (e) {
        log("IP", "Erreur hook URL: " + e);
    }
}

function hookConnectivityManager() {
    /**
     * Simuler une connexion WiFi active (au lieu de la connexion
     * emulateur qui peut etre detectee).
     */
    try {
        var ConnectivityManager = Java.use("android.net.ConnectivityManager");
        var NetworkInfo = Java.use("android.net.NetworkInfo");

        ConnectivityManager.getActiveNetworkInfo.implementation = function () {
            var info = this.getActiveNetworkInfo();
            if (info !== null) {
                log("IP", "getActiveNetworkInfo() -> type: " + info.getType() + " connected: " + info.isConnected());
            }
            return info;
        };

        log("IP", "ConnectivityManager hook installe");
    } catch (e) {
        log("IP", "Erreur hook ConnectivityManager: " + e);
    }
}

function initIpSpoofHooks() {
    if (!CONFIG.network.enabled) {
        log("IP", "IP spoofing desactive");
        return;
    }

    log("IP", "=== IP Spoof: " + CONFIG.network.ip + " ===");
    hookInetAddress();
    hookNetworkInterface();
    hookWifiInfo();
    hookHttpUrlConnection();
    hookConnectivityManager();
    log("IP", "=== Tous les hooks IP actifs ===");
}

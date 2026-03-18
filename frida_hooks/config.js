// ============================================================
//  CONFIG — Configuration centralisee pour tous les hooks Frida
// ============================================================

var CONFIG = {
    // Coordonnees GPS cibles (Paris par defaut)
    latitude: 48.8566,
    longitude: 2.3522,
    altitude: 35.0,
    accuracy: 10.0,       // precision en metres

    // Photo a injecter quand la camera est demandee
    fakePhotoPath: "/sdcard/DCIM/fake_photo.jpg",

    // Identite device spoofee (Samsung Galaxy S21)
    device: {
        brand: "samsung",
        model: "SM-G991B",
        manufacturer: "samsung",
        product: "o1sxeea",
        fingerprint: "samsung/o1sxeea/o1s:13/TP1A.220624.014/G991BXXS7DWBA:user/release-keys",
        hardware: "exynos2100",
        board: "exynos2100"
    },

    // Identite telephonie spoofee
    telephony: {
        imei: "354613091424805",
        operator: "Orange F",
        simOperator: "Orange",
        mcc_mnc: "20801",
        phoneNumber: "+33612345678"
    },

    // Camera2 API settings
    camera: {
        imageFormat: 256,        // ImageFormat.JPEG
        width: 4032,
        height: 3024,
        sensorOrientation: 90,
        lensFacing: 1,           // LENS_FACING_BACK
        cameraId: "0",
        injectIntoPreview: false // true = injecter aussi dans le preview
    },

    // Reseau / IP spoofing
    network: {
        enabled: true,
        ip: "86.234.12.45",          // IP publique spoofee (Free FR par defaut)
        mac: "A4:83:E7:2B:C1:9F",    // Adresse MAC spoofee
        ssid: "Livebox-A7F2",         // Nom WiFi credible
        bssid: "00:1A:2B:3C:4D:5E"   // BSSID WiFi spoofe
    },

    // SSL pinning bypass
    ssl: { enabled: true },

    // Play Integrity bypass
    playIntegrity: { enabled: true },

    // Logging
    verbose: true
};

function log(tag, msg) {
    if (CONFIG.verbose) {
        console.log("[" + tag + "] " + msg);
    }
}

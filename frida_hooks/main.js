// ============================================================
//  MAIN — Loader principal Frida (v3 — sans camera2_hook)
// ============================================================

// === COMPATIBILITY SHIM — Frida 17.x ===
if (typeof Module === 'function' && typeof Module.findExportByName !== 'function') {
    Module.findExportByName = function (moduleName, exportName) {
        if (moduleName === null) {
            if (typeof Module.findGlobalExportByName === 'function') {
                return Module.findGlobalExportByName(exportName);
            }
            var mods = Process.enumerateModules();
            for (var i = 0; i < mods.length; i++) {
                var a = mods[i].findExportByName(exportName);
                if (a !== null) return a;
            }
            return null;
        }
        var mod = Process.findModuleByName(moduleName);
        if (mod === null) return null;
        return mod.findExportByName(exportName);
    };

    Module.findBaseAddress = function (moduleName) {
        var mod = Process.findModuleByName(moduleName);
        return mod !== null ? mod.base : null;
    };

    Module.enumerateExportsSync = function (moduleName) {
        var mod = Process.findModuleByName(moduleName);
        return mod !== null ? mod.enumerateExports() : [];
    };

    console.log("[COMPAT] Module shim installe (Frida 17.x — static API restauree)");
}

// === Diagnostic court ===
console.log("[MAIN] Frida " + Frida.version + " | Runtime: " + Script.runtime + " | PID: " + Process.id + " | Arch: " + Process.arch);

// --- Hooks Java (attendre que le VM soit pret) ---
function startJavaHooks() {
    Java.perform(function () {
        console.log("====================================");
        console.log("  GEO PHOTO v3 — Frida Hooks Active");
        console.log("  Anti-Detection + SSL + GPS + IP");
        console.log("  Camera: pict2cam (externe)");
        console.log("====================================");

        // 1. Anti-detection (hooks Java)
        try {
            initAntiDetectionHooks();
        } catch (e) {
            console.log("[MAIN] Erreur anti_detection: " + e);
        }

        // 2. SSL bypass
        try {
            initSSLBypass();
        } catch (e) {
            console.log("[MAIN] Erreur ssl_bypass: " + e);
        }

        // 3. GPS spoofing
        try {
            initLocationHooks();
        } catch (e) {
            console.log("[MAIN] Erreur spoof_location: " + e);
        }

        // 4. IP spoofing
        try {
            initIpSpoofHooks();
        } catch (e) {
            console.log("[MAIN] Erreur ip_spoof: " + e);
        }

        console.log("====================================");
        console.log("  Hooks charges avec succes");
        console.log("  GPS: " + CONFIG.latitude + ", " + CONFIG.longitude);
        console.log("  Device: " + CONFIG.device.model);
        console.log("  SSL bypass: " + (CONFIG.ssl.enabled ? "ON" : "OFF"));
        console.log("  IP spoof: " + (CONFIG.network.enabled ? CONFIG.network.ip : "OFF"));
        console.log("====================================");

        // Hooks natifs APRES Java
        try {
            hookFridaDetection();
        } catch (e) {
            console.log("[MAIN] Erreur hookFridaDetection (natif): " + e);
        }
    });
}

// Attendre que Java soit disponible avec timeout
var _javaWaitAttempts = 0;
var _javaWaitMax = 150; // 150 * 200ms = 30s max

if (typeof Java !== 'undefined' && Java.available) {
    startJavaHooks();
} else {
    console.log("[MAIN] Java VM pas encore pret, attente...");
    var _javaWait = setInterval(function () {
        _javaWaitAttempts++;
        if (typeof Java !== 'undefined' && Java.available) {
            clearInterval(_javaWait);
            console.log("[MAIN] Java VM detecte apres " + (_javaWaitAttempts * 200) + "ms");
            startJavaHooks();
        } else if (_javaWaitAttempts % 25 === 0 && _javaWaitAttempts > 0) {
            console.log("[MAIN] Java VM toujours pas pret (" + (_javaWaitAttempts * 200) + "ms)...");
        }
        if (_javaWaitAttempts >= _javaWaitMax) {
            clearInterval(_javaWait);
            console.log("[MAIN] ERREUR: Java VM non disponible apres " + (_javaWaitMax * 200) + "ms");
        }
    }, 200);
}

// ============================================================
//  RPC — Interface pour changer la config a chaud
// ============================================================

rpc.exports = {
    setLocation: function (lat, lon, alt, acc) {
        CONFIG.latitude = lat;
        CONFIG.longitude = lon;
        if (alt !== undefined) CONFIG.altitude = alt;
        if (acc !== undefined) CONFIG.accuracy = acc;
        console.log("[RPC] Position mise a jour: " + lat + ", " + lon);
        return { latitude: lat, longitude: lon };
    },

    setPhoto: function (path) {
        CONFIG.fakePhotoPath = path;
        console.log("[RPC] Photo mise a jour: " + path);
        return { path: path };
    },

    getConfig: function () {
        return {
            latitude: CONFIG.latitude,
            longitude: CONFIG.longitude,
            altitude: CONFIG.altitude,
            accuracy: CONFIG.accuracy,
            fakePhotoPath: CONFIG.fakePhotoPath,
            device: CONFIG.device,
            ssl: CONFIG.ssl.enabled,
            ip: CONFIG.network.ip
        };
    },

    setIp: function (ip) {
        CONFIG.network.ip = ip;
        CONFIG.network.enabled = true;
        console.log("[RPC] IP mise a jour: " + ip);
        return { ip: ip };
    },

    setDevice: function (field, value) {
        if (CONFIG.device.hasOwnProperty(field)) {
            CONFIG.device[field] = value;
            console.log("[RPC] Device." + field + " = " + value);
            return true;
        }
        return false;
    }
};

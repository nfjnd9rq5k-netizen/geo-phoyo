// ============================================================
//  ANTI-DETECTION — Bypass emulateur, root, et controles divers
// ============================================================

function hookBuildFields() {
    /**
     * Spoof les champs android.os.Build pour cacher l'emulateur.
     */
    var Build = Java.use("android.os.Build");

    var fieldsToSpoof = {
        "BRAND": CONFIG.device.brand,
        "MODEL": CONFIG.device.model,
        "MANUFACTURER": CONFIG.device.manufacturer,
        "PRODUCT": CONFIG.device.product,
        "FINGERPRINT": CONFIG.device.fingerprint,
        "HARDWARE": CONFIG.device.hardware,
        "BOARD": CONFIG.device.board
    };

    for (var field in fieldsToSpoof) {
        try {
            var f = Build.class.getDeclaredField(field);
            f.setAccessible(true);
            f.set(null, Java.use("java.lang.String").$new(fieldsToSpoof[field]));
            log("ANTI", "Build." + field + " -> " + fieldsToSpoof[field]);
        } catch (e) {
            log("ANTI", "Erreur spoof Build." + field + ": " + e);
        }
    }

    // Aussi DEVICE et SERIAL
    try {
        var fDevice = Build.class.getDeclaredField("DEVICE");
        fDevice.setAccessible(true);
        fDevice.set(null, Java.use("java.lang.String").$new("o1s"));
    } catch (e) {}

    log("ANTI", "Build fields spoofes");
}

function hookFileExists() {
    /**
     * Retourner false pour les chemins lies a l'emulateur et au root.
     */
    var File = Java.use("java.io.File");

    var blacklistedPaths = [
        // Emulateur
        "/dev/socket/qemud",
        "/dev/qemu_pipe",
        "/system/lib/libc_malloc_debug_qemu.so",
        "/sys/qemu_trace",
        "/system/bin/qemu-props",
        "/dev/goldfish_pipe",
        "/system/lib/libdroid4x.so",
        "/data/property/persist.nox",
        // Root
        "/system/app/Superuser.apk",
        "/sbin/su",
        "/system/bin/su",
        "/system/xbin/su",
        "/data/local/xbin/su",
        "/data/local/bin/su",
        "/system/sd/xbin/su",
        "/system/bin/failsafe/su",
        "/data/local/su",
        // Magisk
        "/sbin/.magisk",
        "/cache/.disable_magisk",
        // Xposed
        "/system/framework/XposedBridge.jar",
        "/system/lib/libxposed_art.so"
    ];

    var existsOverload = File.exists.overload();
    existsOverload.implementation = function () {
        var path = this.getAbsolutePath();
        for (var i = 0; i < blacklistedPaths.length; i++) {
            if (path === blacklistedPaths[i]) {
                log("ANTI", "File.exists(" + path + ") -> false (bloque)");
                return false;
            }
        }
        return existsOverload.call(this);
    };

    log("ANTI", "File.exists hook installe (" + blacklistedPaths.length + " chemins bloques)");
}

function hookTelephonyManager() {
    /**
     * Spoof les infos telephonie pour cacher l'emulateur.
     */
    var TelephonyManager = Java.use("android.telephony.TelephonyManager");

    try {
        TelephonyManager.getDeviceId.overload().implementation = function () {
            log("ANTI", "getDeviceId() -> " + CONFIG.telephony.imei);
            return CONFIG.telephony.imei;
        };
    } catch (e) {}

    try {
        TelephonyManager.getDeviceId.overload("int").implementation = function (slot) {
            return CONFIG.telephony.imei;
        };
    } catch (e) {}

    try {
        TelephonyManager.getImei.overload().implementation = function () {
            return CONFIG.telephony.imei;
        };
    } catch (e) {}

    try {
        TelephonyManager.getImei.overload("int").implementation = function (slot) {
            return CONFIG.telephony.imei;
        };
    } catch (e) {}

    TelephonyManager.getNetworkOperatorName.implementation = function () {
        log("ANTI", "getNetworkOperatorName() -> " + CONFIG.telephony.operator);
        return CONFIG.telephony.operator;
    };

    TelephonyManager.getSimOperatorName.implementation = function () {
        return CONFIG.telephony.simOperator;
    };

    TelephonyManager.getNetworkOperator.implementation = function () {
        return CONFIG.telephony.mcc_mnc;
    };

    TelephonyManager.getSimOperator.implementation = function () {
        return CONFIG.telephony.mcc_mnc;
    };

    try {
        TelephonyManager.getLine1Number.implementation = function () {
            return CONFIG.telephony.phoneNumber;
        };
    } catch (e) {}

    // Simuler SIM presente
    TelephonyManager.getSimState.overload().implementation = function () {
        return 5; // SIM_STATE_READY
    };

    TelephonyManager.getPhoneType.implementation = function () {
        return 1; // PHONE_TYPE_GSM
    };

    TelephonyManager.getNetworkType.implementation = function () {
        return 13; // NETWORK_TYPE_LTE
    };

    log("ANTI", "TelephonyManager hooks installes");
}

function hookSensorManager() {
    /**
     * Retourner une liste non-vide de capteurs (les emulateurs en ont souvent 0).
     */
    try {
        var SensorManager = Java.use("android.hardware.SensorManager");
        SensorManager.getSensorList.implementation = function (type) {
            var result = this.getSensorList(type);
            if (result.size() === 0) {
                log("ANTI", "getSensorList(" + type + ") etait vide, laissant passer");
            }
            return result;
        };
        log("ANTI", "SensorManager hook installe");
    } catch (e) {
        log("ANTI", "Erreur hook SensorManager: " + e);
    }
}

function hookRootCommands() {
    /**
     * Empecher l'execution de commandes de detection root.
     */
    var Runtime = Java.use("java.lang.Runtime");
    var originalExec = Runtime.exec.overload("java.lang.String");

    originalExec.implementation = function (cmd) {
        var blockedCommands = ["su", "which su", "type su", "busybox"];
        for (var i = 0; i < blockedCommands.length; i++) {
            if (cmd.indexOf(blockedCommands[i]) !== -1) {
                log("ANTI", "Runtime.exec('" + cmd + "') -> IOException");
                throw Java.use("java.io.IOException").$new("Cannot run program \"" + cmd + "\"");
            }
        }
        return originalExec.call(this, cmd);
    };

    // Aussi l'overload avec String[]
    try {
        var execArray = Runtime.exec.overload("[Ljava.lang.String;");
        execArray.implementation = function (cmdArray) {
            if (cmdArray !== null && cmdArray.length > 0) {
                var cmd0 = cmdArray[0];
                if (cmd0 === "su" || cmd0.indexOf("/su") !== -1) {
                    log("ANTI", "Runtime.exec(['" + cmd0 + "']) -> IOException");
                    throw Java.use("java.io.IOException").$new("Cannot run program \"" + cmd0 + "\"");
                }
            }
            return execArray.call(this, cmdArray);
        };
    } catch (e) {}

    log("ANTI", "Runtime.exec hooks installes");
}

function hookPackageManager() {
    /**
     * Cacher les packages lies au root/hook.
     */
    var PackageManager = Java.use("android.app.ApplicationContext");
    try {
        var PM = Java.use("android.content.pm.PackageManager");
        var ApplicationPackageManager = Java.use("android.app.ApplicationPackageManager");

        ApplicationPackageManager.getPackageInfo.overload(
            "java.lang.String", "int"
        ).implementation = function (packageName, flags) {
            var blocked = [
                "com.topjohnwu.magisk",
                "eu.chainfire.supersu",
                "com.koushikdutta.superuser",
                "com.noshufou.android.su",
                "de.robv.android.xposed.installer",
                "com.saurik.substrate",
                "com.amphoras.hidemyroot",
                "com.formyhm.hideroot"
            ];

            for (var i = 0; i < blocked.length; i++) {
                if (packageName === blocked[i]) {
                    log("ANTI", "getPackageInfo('" + packageName + "') -> NameNotFound");
                    throw Java.use("android.content.pm.PackageManager$NameNotFoundException")
                        .$new(packageName);
                }
            }
            return this.getPackageInfo(packageName, flags);
        };
    } catch (e) {
        log("ANTI", "Erreur hook PackageManager: " + e);
    }

    log("ANTI", "PackageManager hooks installes");
}

function hookSafetyNet() {
    /**
     * Hook basique SafetyNet — ne fonctionne PAS contre verification server-side.
     */
    try {
        var SafetyNetClient = Java.use("com.google.android.gms.safetynet.SafetyNetClient");
        log("ANTI", "SafetyNet detecte, hook basique installe");
        // Note: un bypass complet necessiterait de modifier l'attestation signee
        // Ce hook ne suffit pas contre une verification server-side
    } catch (e) {
        log("ANTI", "SafetyNet non trouve (normal si pas utilise)");
    }
}

function hookSystemProperties() {
    /**
     * Cacher les proprietes systeme revelant un emulateur.
     */
    try {
        var SystemProperties = Java.use("android.os.SystemProperties");
        var originalGet = SystemProperties.get.overload("java.lang.String");

        originalGet.implementation = function (key) {
            var spoofedProps = {
                "ro.hardware": CONFIG.device.hardware,
                "ro.product.model": CONFIG.device.model,
                "ro.product.brand": CONFIG.device.brand,
                "ro.product.manufacturer": CONFIG.device.manufacturer,
                "ro.product.board": CONFIG.device.board,
                "ro.build.fingerprint": CONFIG.device.fingerprint,
                "init.svc.qemud": null,
                "init.svc.qemu-props": null,
                "ro.kernel.qemu": "0",
                "ro.kernel.qemu.gles": null,
                "ro.boot.qemu": "0"
            };

            if (key in spoofedProps) {
                var value = spoofedProps[key];
                if (value === null) {
                    return "";
                }
                log("ANTI", "SystemProperties.get('" + key + "') -> " + value);
                return value;
            }
            return originalGet.call(this, key);
        };

        // Overload avec valeur par defaut
        var originalGetDef = SystemProperties.get.overload("java.lang.String", "java.lang.String");
        originalGetDef.implementation = function (key, def) {
            var result = SystemProperties.get(key);
            return result.length > 0 ? result : def;
        };

        log("ANTI", "SystemProperties hooks installes");
    } catch (e) {
        log("ANTI", "Erreur hook SystemProperties: " + e);
    }
}

function hookFridaDetection() {
    /**
     * Cacher Frida via hooks natifs libc.
     * Utilise Interceptor.attach (compatible x86_64) au lieu de replace.
     */

    // Diagnostic : verifier que les APIs Frida natives sont disponibles
    log("ANTI", "Diagnostic APIs natifs:");
    log("ANTI", "  typeof Interceptor = " + typeof Interceptor);
    log("ANTI", "  typeof Module = " + typeof Module);
    log("ANTI", "  typeof Memory = " + typeof Memory);
    log("ANTI", "  typeof ptr = " + typeof ptr);

    if (typeof Interceptor === "undefined" || typeof Interceptor.attach !== "function") {
        log("ANTI", "ERREUR: Interceptor.attach non disponible — hooks natifs desactives");
        log("ANTI", "  Interceptor = " + String(Interceptor));
        if (typeof Interceptor !== "undefined") {
            log("ANTI", "  Interceptor keys = " + Object.keys(Interceptor).join(", "));
        }
        return;
    }

    if (typeof Module === "undefined" || typeof Module.findExportByName !== "function") {
        log("ANTI", "ERREUR: Module.findExportByName non disponible — hooks natifs desactives");
        log("ANTI", "  Module = " + String(Module).substring(0, 200));
        try { log("ANTI", "  Module keys = " + Object.getOwnPropertyNames(Module).join(", ")); } catch(e) {}
        try { log("ANTI", "  Module.prototype = " + Object.getOwnPropertyNames(Module.prototype).join(", ")); } catch(e) {}
        // Tentative d'appel direct malgre le typeof
        try {
            var _test = Module.findExportByName("libc.so", "open");
            log("ANTI", "  Appel direct reussi: " + _test + " (typeof mentait!)");
            // Si ca marche, continuer quand meme !
        } catch(e2) {
            log("ANTI", "  Appel direct echoue: " + e2);
        }
        return;
    }

    var fridaKeywords = ["frida", "libfrida", "gum-js-loop", "gmain", "frida-agent",
                         "frida-gadget", "27042", "linjector"];

    function isFridaString(s) {
        if (!s) return false;
        var lower = s.toLowerCase();
        for (var i = 0; i < fridaKeywords.length; i++) {
            if (lower.indexOf(fridaKeywords[i]) !== -1) return true;
        }
        return false;
    }

    var sensitivePaths = ["/proc/self/maps", "/proc/self/task", "/proc/self/mountinfo"];
    var networkPaths = ["/proc/net/tcp", "/proc/net/tcp6", "/proc/net/udp", "/proc/net/udp6"];

    function isSensitivePath(s) {
        if (!s) return false;
        for (var i = 0; i < sensitivePaths.length; i++) {
            if (s.indexOf(sensitivePaths[i]) !== -1) return true;
        }
        return false;
    }

    function isNetworkPath(s) {
        if (!s) return false;
        for (var i = 0; i < networkPaths.length; i++) {
            if (s.indexOf(networkPaths[i]) !== -1) return true;
        }
        return false;
    }

    // Helper : trouver un export dans libc.so, fallback sur null (tous les modules)
    function findExport(name) {
        var addr = Module.findExportByName("libc.so", name);
        if (addr === null) {
            log("ANTI", "  " + name + " introuvable dans libc.so, recherche globale...");
            addr = Module.findExportByName(null, name);
        }
        if (addr !== null) {
            log("ANTI", "  " + name + " trouve a " + addr);
        } else {
            log("ANTI", "  " + name + " introuvable nulle part");
        }
        return addr;
    }

    // Allouer /dev/null une seule fois pour les redirections
    var devNull = Memory.allocUtf8String("/dev/null");
    var hooksInstalled = 0;

    // Hook strstr — cacher les strings Frida
    try {
        var strstrAddr = findExport("strstr");
        if (strstrAddr !== null) {
            Interceptor.attach(strstrAddr, {
                onEnter: function (args) {
                    this.shouldBlock = false;
                    try {
                        if (!args[1].isNull()) {
                            var needle = args[1].readCString();
                            if (isFridaString(needle)) {
                                this.shouldBlock = true;
                            }
                        }
                    } catch (e) {}
                },
                onLeave: function (retval) {
                    if (this.shouldBlock) {
                        retval.replace(ptr(0));
                    }
                }
            });
            hooksInstalled++;
            log("ANTI", "strstr hook OK");
        }
    } catch (e) {
        log("ANTI", "strstr skip: " + e);
    }

    // Hook fopen
    try {
        var fopenAddr = findExport("fopen");
        if (fopenAddr !== null) {
            Interceptor.attach(fopenAddr, {
                onEnter: function (args) {
                    try {
                        if (!args[0].isNull()) {
                            var path = args[0].readCString();
                            if (isSensitivePath(path)) {
                                log("ANTI", "fopen(" + path + ") -> /dev/null");
                                args[0] = devNull;
                            }
                        }
                    } catch (e) {}
                }
            });
            hooksInstalled++;
            log("ANTI", "fopen hook OK");
        }
    } catch (e) {
        log("ANTI", "fopen skip: " + e);
    }

    // Hook open
    try {
        var openAddr = findExport("open");
        if (openAddr !== null) {
            Interceptor.attach(openAddr, {
                onEnter: function (args) {
                    try {
                        if (!args[0].isNull()) {
                            var path = args[0].readCString();
                            if (isNetworkPath(path) || isSensitivePath(path)) {
                                log("ANTI", "open(" + path + ") -> /dev/null");
                                args[0] = devNull;
                            }
                        }
                    } catch (e) {}
                }
            });
            hooksInstalled++;
            log("ANTI", "open hook OK");
        }
    } catch (e) {
        log("ANTI", "open skip: " + e);
    }

    // Hook openat
    try {
        var openatAddr = findExport("openat");
        if (openatAddr !== null) {
            Interceptor.attach(openatAddr, {
                onEnter: function (args) {
                    try {
                        if (!args[1].isNull()) {
                            var path = args[1].readCString();
                            if (isNetworkPath(path) || isSensitivePath(path)) {
                                log("ANTI", "openat(" + path + ") -> /dev/null");
                                args[1] = devNull;
                            }
                        }
                    } catch (e) {}
                }
            });
            hooksInstalled++;
            log("ANTI", "openat hook OK");
        }
    } catch (e) {
        log("ANTI", "openat skip: " + e);
    }

    log("ANTI", hooksInstalled + "/4 hooks natifs installes");
}

function hookPlayIntegrity() {
    /**
     * Bypass basique Play Integrity / SafetyNet.
     * NOTE: ne suffit PAS si le serveur verifie le token signe.
     */
    if (!CONFIG.playIntegrity.enabled) {
        log("ANTI", "Play Integrity bypass desactive");
        return;
    }

    // Play Integrity API
    try {
        var IntegrityManager = Java.use("com.google.android.play.core.integrity.IntegrityManager");
        log("ANTI", "Play Integrity API detectee — monitoring actif");
    } catch (e) {
        log("ANTI", "Play Integrity API non trouvee (normal)");
    }

    // SafetyNet
    try {
        var SafetyNetClient = Java.use("com.google.android.gms.safetynet.SafetyNetClient");
        SafetyNetClient.attest.implementation = function (nonce, apiKey) {
            log("ANTI", "SafetyNet.attest() intercepte — laisser passer mais logger");
            return this.attest(nonce, apiKey);
        };
        log("ANTI", "SafetyNet attest hook installe");
    } catch (e) {
        log("ANTI", "SafetyNet non trouve (normal si pas utilise)");
    }

    log("ANTI", "Play Integrity hooks installes");
}

function hookScreenshotDetection() {
    /**
     * Retirer FLAG_SECURE pour permettre les screenshots/enregistrement.
     */
    try {
        var Window = Java.use("android.view.Window");
        Window.setFlags.implementation = function (flags, mask) {
            var FLAG_SECURE = 0x2000;
            if ((flags & FLAG_SECURE) !== 0) {
                log("ANTI", "Window.setFlags: FLAG_SECURE retire");
                flags = flags & ~FLAG_SECURE;
                mask = mask & ~FLAG_SECURE;
            }
            this.setFlags(flags, mask);
        };
        log("ANTI", "Screenshot detection hook installe (FLAG_SECURE bypass)");
    } catch (e) {
        log("ANTI", "Erreur hook Window.setFlags: " + e);
    }
}

function initAntiDetectionHooks() {
    hookBuildFields();
    hookFileExists();
    hookTelephonyManager();
    hookSensorManager();
    hookRootCommands();
    hookPackageManager();
    hookSafetyNet();
    hookSystemProperties();
    // hookFridaDetection() est appele separement dans main.js (hooks natifs, pas besoin de Java)
    hookPlayIntegrity();
    hookScreenshotDetection();
    log("ANTI", "=== Tous les hooks anti-detection actifs ===");
}

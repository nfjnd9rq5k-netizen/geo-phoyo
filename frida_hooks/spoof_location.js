// ============================================================
//  SPOOF LOCATION — Hook GPS pour injecter de fausses coords
// ============================================================

function makeFakeLocation(provider) {
    var Location = Java.use("android.location.Location");
    var loc = Location.$new(provider || "gps");
    loc.setLatitude(CONFIG.latitude);
    loc.setLongitude(CONFIG.longitude);
    loc.setAltitude(CONFIG.altitude);
    loc.setAccuracy(CONFIG.accuracy);
    loc.setTime(Java.use("java.lang.System").currentTimeMillis());
    // Eviter detection "location trop vieille"
    try {
        loc.setElapsedRealtimeNanos(
            Java.use("android.os.SystemClock").elapsedRealtimeNanos()
        );
    } catch (e) {
        // API pas dispo sur vieilles versions
    }
    return loc;
}

function hookLocationManager() {
    var LocationManager = Java.use("android.location.LocationManager");

    // 1. getLastKnownLocation
    LocationManager.getLastKnownLocation.overload("java.lang.String").implementation = function (provider) {
        log("GPS", "getLastKnownLocation(" + provider + ") -> fake");
        return makeFakeLocation(provider);
    };

    // 2. requestLocationUpdates — tous les overloads avec LocationListener
    var overloads = LocationManager.requestLocationUpdates.overloads;
    for (var i = 0; i < overloads.length; i++) {
        (function (overload) {
            overload.implementation = function () {
                log("GPS", "requestLocationUpdates intercepte (overload " + arguments.length + " args)");
                // Trouver le LocationListener dans les arguments
                for (var j = 0; j < arguments.length; j++) {
                    var arg = arguments[j];
                    if (arg !== null && arg.$className !== undefined) {
                        try {
                            var LocationListener = Java.use("android.location.LocationListener");
                            var listener = Java.cast(arg, LocationListener);
                            // Envoyer une fausse position immediatement
                            setTimeout(function () {
                                Java.perform(function () {
                                    try {
                                        listener.onLocationChanged(makeFakeLocation("gps"));
                                        log("GPS", "Fausse position envoyee au listener");
                                    } catch (e) {
                                        log("GPS", "Erreur envoi position: " + e);
                                    }
                                });
                            }, 500);
                            break;
                        } catch (e) {
                            // Pas un LocationListener, continuer
                        }
                    }
                }
                // Ne pas appeler l'original — empeche le vrai GPS
            };
        })(overloads[i]);
    }

    // 3. isProviderEnabled — toujours true
    LocationManager.isProviderEnabled.overload("java.lang.String").implementation = function (provider) {
        log("GPS", "isProviderEnabled(" + provider + ") -> true");
        return true;
    };

    log("GPS", "LocationManager hooks installes");
}

function hookFusedLocationProvider() {
    try {
        var FusedClient = Java.use("com.google.android.gms.location.FusedLocationProviderClient");

        FusedClient.getLastLocation.implementation = function () {
            log("GPS", "FusedLocationProviderClient.getLastLocation() -> fake");
            var Tasks = Java.use("com.google.android.gms.tasks.Tasks");
            return Tasks.forResult(makeFakeLocation("fused"));
        };

        // requestLocationUpdates
        var fusedOverloads = FusedClient.requestLocationUpdates.overloads;
        for (var i = 0; i < fusedOverloads.length; i++) {
            (function (overload) {
                overload.implementation = function () {
                    log("GPS", "FusedLocationProviderClient.requestLocationUpdates intercepte");
                    // Trouver le callback et lui envoyer une fausse position
                    for (var j = 0; j < arguments.length; j++) {
                        var arg = arguments[j];
                        if (arg !== null && arg.$className !== undefined) {
                            try {
                                var LocationCallback = Java.use("com.google.android.gms.location.LocationCallback");
                                var callback = Java.cast(arg, LocationCallback);
                                setTimeout(function () {
                                    Java.perform(function () {
                                        try {
                                            var LocationResult = Java.use("com.google.android.gms.location.LocationResult");
                                            var ArrayList = Java.use("java.util.ArrayList");
                                            var list = ArrayList.$new();
                                            list.add(makeFakeLocation("fused"));
                                            var result = LocationResult.create(list);
                                            callback.onLocationResult(result);
                                            log("GPS", "Fausse position envoyee via FusedCallback");
                                        } catch (e) {
                                            log("GPS", "Erreur FusedCallback: " + e);
                                        }
                                    });
                                }, 500);
                                break;
                            } catch (e) {
                                // Pas un LocationCallback
                            }
                        }
                    }
                    // Retourner une Task vide
                    var Tasks = Java.use("com.google.android.gms.tasks.Tasks");
                    return Tasks.forResult(null);
                };
            })(fusedOverloads[i]);
        }

        log("GPS", "FusedLocationProviderClient hooks installes");
    } catch (e) {
        log("GPS", "Google Play Services non trouve, skip FusedLocation hooks");
    }
}

function hookMockLocationSetting() {
    try {
        var Secure = Java.use("android.provider.Settings$Secure");
        var originalGetString = Secure.getString.overload(
            "android.content.ContentResolver", "java.lang.String"
        );
        originalGetString.implementation = function (resolver, name) {
            if (name === "mock_location") {
                log("GPS", "Settings.Secure.getString(mock_location) -> 0");
                return "0";
            }
            return originalGetString.call(this, resolver, name);
        };
        log("GPS", "Mock location setting hook installe");
    } catch (e) {
        log("GPS", "Erreur hook Settings.Secure: " + e);
    }
}

function initLocationHooks() {
    hookLocationManager();
    hookFusedLocationProvider();
    hookMockLocationSetting();
    log("GPS", "=== Tous les hooks GPS actifs ===");
    log("GPS", "Position: " + CONFIG.latitude + ", " + CONFIG.longitude);
}

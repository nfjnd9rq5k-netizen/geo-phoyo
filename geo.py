"""
=============================================================
  GEO MODIFIER — Modification propre de geolocalisation EXIF
=============================================================

Ce script modifie les coordonnees GPS d'une photo JPEG en veillant
a garder TOUTES les metadonnees coherentes entre elles pour eviter
toute detection.

Utilisation :
    python geo.py photo.jpg 48.8566 2.3522
    python geo.py photo.jpg 48.8566 2.3522 --altitude 35
    python geo.py photo.jpg 48.8566 2.3522 --output nouvelle_photo.jpg
"""

import argparse
import ctypes
import io
import os
import random
import re
import struct
import sys
from datetime import datetime, timedelta

import piexif
from timezonefinder import TimezoneFinder
import pytz


# ──────────────────────────────────────────────
#  MONKEY-PATCH PIEXIF — Support OffsetTime
# ──────────────────────────────────────────────

def monkey_patch_piexif():
    """Ajoute les tags OffsetTime non supportes nativement par piexif."""
    tags_to_add = {
        36880: {"name": "OffsetTime", "type": piexif.TYPES.Ascii},
        36881: {"name": "OffsetTimeOriginal", "type": piexif.TYPES.Ascii},
        36882: {"name": "OffsetTimeDigitized", "type": piexif.TYPES.Ascii},
    }
    for tag_id, tag_info in tags_to_add.items():
        if tag_id not in piexif.TAGS.get("Exif", {}):
            piexif.TAGS.setdefault("Exif", {})[tag_id] = tag_info
        if not hasattr(piexif.ExifIFD, tag_info["name"]):
            setattr(piexif.ExifIFD, tag_info["name"], tag_id)

monkey_patch_piexif()


# ──────────────────────────────────────────────
#  FONCTIONS UTILITAIRES
# ──────────────────────────────────────────────

# GPSVersionID typiques par fabricant
CAMERA_GPS_VERSION = {
    b'apple':    (2, 2, 0, 0),
    b'samsung':  (2, 3, 0, 0),
    b'google':   (2, 3, 0, 0),
    b'huawei':   (2, 3, 0, 0),
    b'xiaomi':   (2, 3, 0, 0),
    b'nikon':    (2, 3, 0, 0),
    b'canon':    (2, 3, 0, 0),
    b'sony':     (2, 3, 0, 0),
    b'fujifilm': (2, 3, 0, 0),
    b'olympus':  (2, 3, 0, 0),
    b'panasonic': (2, 3, 0, 0),
}

# Denominateurs GPS typiques par fabricant
CAMERA_GPS_DENOMINATORS = {
    b'apple':    100,
    b'samsung':  10000,
    b'google':   10000,
    b'huawei':   10000,
    b'xiaomi':   10000,
    b'nikon':    1000000,
    b'canon':    100,
    b'sony':     100,
    b'fujifilm': 100,
    b'olympus':  100,
    b'panasonic': 100,
}


def decimal_to_dms(decimal_degree, seconds_denom=10000):
    """
    Convertit un nombre decimal en Degres/Minutes/Secondes EXIF.
    Le denominateur des secondes est configurable pour matcher le profil camera.
    """
    is_negative = decimal_degree < 0
    decimal_degree = abs(decimal_degree)

    degrees = int(decimal_degree)
    minutes_float = (decimal_degree - degrees) * 60
    minutes = int(minutes_float)
    seconds_float = (minutes_float - minutes) * 60

    seconds_numerator = int(round(seconds_float * seconds_denom))
    # LSB jitter — simulates real GPS sensor noise (~0.3m for denom=10000)
    seconds_numerator += random.choice([-2, -1, 0, 0, 0, 1, 2])
    seconds_numerator = max(0, seconds_numerator)

    return (
        (degrees, 1),
        (minutes, 1),
        (seconds_numerator, seconds_denom)
    ), is_negative


def get_timezone_for_coords(lat, lon):
    """Trouve le fuseau horaire correspondant a des coordonnees GPS."""
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lon)
    if tz_name is None:
        offset_hours = round(lon / 15)
        return f"Etc/GMT{-offset_hours:+d}" if offset_hours != 0 else "UTC"
    return tz_name


def get_realistic_altitude(lat, lon, manual_altitude=None):
    """Retourne une altitude realiste pour les coordonnees donnees."""
    if manual_altitude is not None:
        return manual_altitude
    return random.uniform(20, 80)


def set_file_creation_time(path, creation_timestamp):
    """Windows-specific: set file creation time using kernel32.SetFileTime."""
    if sys.platform != 'win32':
        return
    try:
        # Convert Unix timestamp to Windows FILETIME (100-nanosecond intervals since 1601-01-01)
        EPOCH_DIFF = 116444736000000000  # difference between 1601 and 1970 in 100ns
        ft = int(creation_timestamp * 10000000) + EPOCH_DIFF
        ft_low = ft & 0xFFFFFFFF
        ft_high = (ft >> 32) & 0xFFFFFFFF

        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
        FILE_ATTRIBUTE_NORMAL = 0x80

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateFileW(
            str(path), GENERIC_WRITE, 0, None,
            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS, None
        )
        if handle == -1:
            return

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                         ("dwHighDateTime", ctypes.c_uint32)]

        ctime = FILETIME(ft_low, ft_high)
        kernel32.SetFileTime(handle, ctypes.byref(ctime), None, None)
        kernel32.CloseHandle(handle)
    except Exception:
        pass  # Non-critical: best effort on Windows


def preserve_file_timestamps(original_path, new_path):
    """Copie les dates du fichier original vers le nouveau fichier."""
    stat = os.stat(original_path)
    os.utime(new_path, (stat.st_atime, stat.st_mtime))
    # On Windows, also restore creation time
    if sys.platform == 'win32':
        set_file_creation_time(new_path, stat.st_ctime)


def get_camera_make(exif_dict):
    """Extrait le Make de l'appareil photo depuis l'EXIF."""
    make = exif_dict.get("0th", {}).get(piexif.ImageIFD.Make, b'')
    if isinstance(make, str):
        make = make.encode('ascii', errors='ignore')
    return make.lower().strip(b'\x00 ')


def get_original_gps_precision(exif_dict):
    """Lit le denominateur GPS original pour reproduire la meme precision."""
    gps = exif_dict.get("GPS", {})
    lat = gps.get(piexif.GPSIFD.GPSLatitude)
    if lat and len(lat) >= 3:
        return lat[2][1]  # denominateur des secondes
    return None


def get_gps_denom_for_camera(make):
    """Retourne le denominateur GPS typique pour un fabricant donne."""
    for brand, denom in CAMERA_GPS_DENOMINATORS.items():
        if brand in make:
            return denom
    return 10000  # defaut


def get_gps_version_for_camera(make):
    """Retourne le GPSVersionID typique pour un fabricant donne."""
    for brand, version in CAMERA_GPS_VERSION.items():
        if brand in make:
            return version
    return (2, 3, 0, 0)  # defaut


def generate_subsec_time(original_value):
    """
    Genere un SubSecTime realiste avec le meme nombre de chiffres que l'original.
    """
    if original_value is None:
        return None
    if isinstance(original_value, bytes):
        original_value = original_value.decode('ascii', errors='ignore')
    num_digits = len(original_value.strip())
    if num_digits <= 0:
        return None
    max_val = 10 ** num_digits - 1
    while True:
        new_val = random.randint(0, max_val)
        # Reject round multiples of 100 for 3+ digit values (synthetic pattern)
        if num_digits >= 3 and new_val % 100 == 0:
            continue
        break
    return str(new_val).zfill(num_digits).encode('ascii')


def generate_realistic_dop(original_dop=None):
    """
    Genere un DOP realiste. Si l'original existait, perturbe legerement
    en gardant le meme denominateur.
    """
    if original_dop is not None:
        num, denom = original_dop
        value = num / denom
        # Perturbation de +/- 20%
        new_value = value * random.uniform(0.8, 1.2)
        new_value = max(1.0, min(30.0, new_value))
        return (int(round(new_value * denom)), denom)
    else:
        # Distribution log-normale: mediane ~1.6, queue longue — realiste
        dop_value = random.lognormvariate(0.5, 0.7)
        dop_value = max(0.8, min(25.0, dop_value))
        return (int(round(dop_value * 10)), 10)


# ──────────────────────────────────────────────
#  GESTION XMP (segment APP1 avec namespace Adobe)
# ──────────────────────────────────────────────

XMP_HEADER = b'http://ns.adobe.com/xap/1.0/\x00'
XMP_EXT_HEADER = b'http://ns.adobe.com/xmp/extension/\x00'


def find_xmp_segment(jpeg_bytes):
    """
    Localise le segment XMP standard dans les bytes JPEG.
    Retourne (offset_debut_segment, longueur_segment, contenu_xml) ou None.
    """
    pos = 2  # skip SOI (FF D8)
    while pos < len(jpeg_bytes) - 4:
        if jpeg_bytes[pos] != 0xFF:
            break
        marker = jpeg_bytes[pos + 1]
        if marker == 0xD9:  # EOI
            break
        if marker == 0xDA:  # SOS — fin des segments metadata
            break
        seg_length = struct.unpack('>H', jpeg_bytes[pos + 2:pos + 4])[0]
        seg_data = jpeg_bytes[pos + 4:pos + 2 + seg_length]

        # APP1 = 0xE1
        if marker == 0xE1 and seg_data.startswith(XMP_HEADER):
            xml_data = seg_data[len(XMP_HEADER):]
            return (pos, 2 + seg_length, xml_data)

        pos += 2 + seg_length

    return None


def find_extended_xmp_segments(jpeg_bytes):
    """
    Localise tous les segments XMP etendus (APP1 avec XMP_EXT_HEADER).
    Retourne une liste de (offset, longueur) pour chaque segment trouve.
    """
    segments = []
    pos = 2  # skip SOI
    while pos < len(jpeg_bytes) - 4:
        if jpeg_bytes[pos] != 0xFF:
            break
        marker = jpeg_bytes[pos + 1]
        if marker == 0xD9 or marker == 0xDA:
            break
        seg_length = struct.unpack('>H', jpeg_bytes[pos + 2:pos + 4])[0]
        seg_data = jpeg_bytes[pos + 4:pos + 2 + seg_length]

        if marker == 0xE1 and seg_data.startswith(XMP_EXT_HEADER):
            segments.append((pos, 2 + seg_length))

        pos += 2 + seg_length
    return segments


def clean_extended_xmp_gps(jpeg_bytes):
    """
    Nettoie les coordonnees GPS et les champs de localisation
    dans les segments XMP etendus.
    """
    gps_patterns = [
        rb'exif:GPS[A-Za-z]+="[^"]*"',
        rb'<exif:GPS[A-Za-z]+>[^<]*</exif:GPS[A-Za-z]+>',
        rb'photoshop:City="[^"]*"',
        rb'photoshop:State="[^"]*"',
        rb'photoshop:Country="[^"]*"',
        rb'<photoshop:City>[^<]*</photoshop:City>',
        rb'<photoshop:State>[^<]*</photoshop:State>',
        rb'<photoshop:Country>[^<]*</photoshop:Country>',
        rb'Iptc4xmpCore:Location="[^"]*"',
        rb'Iptc4xmpCore:CountryCode="[^"]*"',
        rb'<Iptc4xmpCore:Location>[^<]*</Iptc4xmpCore:Location>',
        rb'<Iptc4xmpCore:CountryCode>[^<]*</Iptc4xmpCore:CountryCode>',
    ]

    segments = find_extended_xmp_segments(jpeg_bytes)
    if not segments:
        return jpeg_bytes

    # Process segments in reverse order to preserve offsets
    for seg_offset, seg_length in reversed(segments):
        seg_data = jpeg_bytes[seg_offset + 4:seg_offset + seg_length]
        # Extended XMP: header + 32-byte MD5 + 4-byte total length + 4-byte offset + XML
        header_len = len(XMP_EXT_HEADER)
        if len(seg_data) < header_len + 40:
            continue
        ext_header = seg_data[:header_len + 40]
        xml_part = seg_data[header_len + 40:]

        modified = False
        for pattern in gps_patterns:
            new_xml, count = re.subn(pattern, b'', xml_part)
            if count > 0:
                xml_part = new_xml
                modified = True

        if modified:
            new_seg_data = ext_header + xml_part
            new_seg_length = len(new_seg_data) + 2
            new_segment = (struct.pack('>BB', 0xFF, 0xE1) +
                           struct.pack('>H', new_seg_length) + new_seg_data)
            jpeg_bytes = (jpeg_bytes[:seg_offset] + new_segment +
                          jpeg_bytes[seg_offset + seg_length:])

    return jpeg_bytes


def modify_xmp_gps(xml_bytes, lat, lon, alt, utc_dt, local_dt_str=None, offset_str=None):
    """
    Modifie les coordonnees GPS, synchronise les dates XMP,
    supprime l'historique et les champs de localisation dans le XML XMP.
    """
    xml_str = xml_bytes.decode('utf-8', errors='replace')

    # Format DMS pour XMP: "48,51.396N" ou "48,51,23.76N"
    lat_ref = 'S' if lat < 0 else 'N'
    lon_ref = 'W' if lon < 0 else 'E'
    abs_lat = abs(lat)
    abs_lon = abs(lon)
    lat_deg = int(abs_lat)
    lat_min = (abs_lat - lat_deg) * 60
    lon_deg = int(abs_lon)
    lon_min = (abs_lon - lon_deg) * 60

    xmp_lat = f"{lat_deg},{lat_min:.6f}{lat_ref}"
    xmp_lon = f"{lon_deg},{lon_min:.6f}{lon_ref}"

    # Remplacer les coordonnees GPS
    gps_replacements = [
        (r'exif:GPSLatitude="[^"]*"', f'exif:GPSLatitude="{xmp_lat}"'),
        (r'exif:GPSLongitude="[^"]*"', f'exif:GPSLongitude="{xmp_lon}"'),
        (r'exif:GPSAltitude="[^"]*"', f'exif:GPSAltitude="{int(alt * 100)}/100"'),
        (r'exif:GPSAltitudeRef="[^"]*"', 'exif:GPSAltitudeRef="0"'),
        # Tags sous forme d'elements
        (r'<exif:GPSLatitude>[^<]*</exif:GPSLatitude>',
         f'<exif:GPSLatitude>{xmp_lat}</exif:GPSLatitude>'),
        (r'<exif:GPSLongitude>[^<]*</exif:GPSLongitude>',
         f'<exif:GPSLongitude>{xmp_lon}</exif:GPSLongitude>'),
        (r'<exif:GPSAltitude>[^<]*</exif:GPSAltitude>',
         f'<exif:GPSAltitude>{int(alt * 100)}/100</exif:GPSAltitude>'),
    ]

    # GPS timestamp XMP
    gps_ts = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    gps_replacements += [
        (r'exif:GPSTimeStamp="[^"]*"', f'exif:GPSTimeStamp="{gps_ts}"'),
        (r'<exif:GPSTimeStamp>[^<]*</exif:GPSTimeStamp>',
         f'<exif:GPSTimeStamp>{gps_ts}</exif:GPSTimeStamp>'),
    ]

    for pattern, replacement in gps_replacements:
        xml_str = re.sub(pattern, replacement, xml_str)

    # Supprimer les champs de localisation IPTC/Photoshop dans XMP
    location_tags_attr = [
        r'\s*photoshop:City="[^"]*"',
        r'\s*photoshop:State="[^"]*"',
        r'\s*photoshop:Country="[^"]*"',
        r'\s*photoshop:Category="[^"]*"',
        r'\s*photoshop:SupplementalCategories="[^"]*"',
        r'\s*Iptc4xmpCore:Location="[^"]*"',
        r'\s*Iptc4xmpCore:CountryCode="[^"]*"',
        r'\s*dc:coverage="[^"]*"',
        r'\s*dc:Coverage="[^"]*"',
    ]
    location_tags_elem = [
        r'\s*<photoshop:City>[^<]*</photoshop:City>',
        r'\s*<photoshop:State>[^<]*</photoshop:State>',
        r'\s*<photoshop:Country>[^<]*</photoshop:Country>',
        r'\s*<photoshop:Category>[^<]*</photoshop:Category>',
        r'\s*<photoshop:SupplementalCategories>[^<]*</photoshop:SupplementalCategories>',
        r'\s*<Iptc4xmpCore:Location>[^<]*</Iptc4xmpCore:Location>',
        r'\s*<Iptc4xmpCore:CountryCode>[^<]*</Iptc4xmpCore:CountryCode>',
        r'\s*<dc:coverage>[^<]*</dc:coverage>',
        r'\s*<dc:Coverage>[^<]*</dc:Coverage>',
    ]

    for pattern in location_tags_attr + location_tags_elem:
        xml_str = re.sub(pattern, '', xml_str)

    # ── A2: Synchroniser les dates XMP avec le DateTime EXIF ──
    if local_dt_str and offset_str:
        # Build XMP date format: "2024-06-15T14:30:00+02:00"
        # local_dt_str is "YYYY:MM:DD HH:MM:SS", offset_str is "+02:00"
        xmp_date = local_dt_str.replace(":", "-", 2).replace(" ", "T", 1) + offset_str
        date_tags_attr = [
            (r'xmp:ModifyDate="[^"]*"', f'xmp:ModifyDate="{xmp_date}"'),
            (r'xmp:MetadataDate="[^"]*"', f'xmp:MetadataDate="{xmp_date}"'),
            (r'xmp:CreateDate="[^"]*"', f'xmp:CreateDate="{xmp_date}"'),
        ]
        date_tags_elem = [
            (r'<xmp:ModifyDate>[^<]*</xmp:ModifyDate>', f'<xmp:ModifyDate>{xmp_date}</xmp:ModifyDate>'),
            (r'<xmp:MetadataDate>[^<]*</xmp:MetadataDate>', f'<xmp:MetadataDate>{xmp_date}</xmp:MetadataDate>'),
            (r'<xmp:CreateDate>[^<]*</xmp:CreateDate>', f'<xmp:CreateDate>{xmp_date}</xmp:CreateDate>'),
        ]
        for pattern, replacement in date_tags_attr + date_tags_elem:
            xml_str = re.sub(pattern, replacement, xml_str)

    # ── A3: Supprimer xmpMM:History, DerivedFrom, DocumentID, InstanceID ──
    xml_str = re.sub(r'\s*<xmpMM:History>.*?</xmpMM:History>', '', xml_str, flags=re.DOTALL)
    xml_str = re.sub(r'\s*<xmpMM:DerivedFrom[^/]*/>', '', xml_str, flags=re.DOTALL)
    xml_str = re.sub(r'\s*<xmpMM:DerivedFrom>.*?</xmpMM:DerivedFrom>', '', xml_str, flags=re.DOTALL)
    xml_str = re.sub(r'\s*xmpMM:DocumentID="[^"]*"', '', xml_str)
    xml_str = re.sub(r'\s*xmpMM:InstanceID="[^"]*"', '', xml_str)
    xml_str = re.sub(r'\s*<xmpMM:DocumentID>[^<]*</xmpMM:DocumentID>', '', xml_str)
    xml_str = re.sub(r'\s*<xmpMM:InstanceID>[^<]*</xmpMM:InstanceID>', '', xml_str)

    # ── A4: Supprimer tiff:Software dans XMP ──
    xml_str = re.sub(r'\s*tiff:Software="[^"]*"', '', xml_str)
    xml_str = re.sub(r'\s*<tiff:Software>[^<]*</tiff:Software>', '', xml_str)

    return xml_str.encode('utf-8')


def replace_xmp_segment(jpeg_bytes, new_xml_bytes):
    """
    Remplace le segment XMP dans les bytes JPEG.
    Utilise le padding XMP pour conserver la meme taille si possible.
    """
    result = find_xmp_segment(jpeg_bytes)
    if result is None:
        return jpeg_bytes

    seg_offset, seg_length, old_xml = result
    old_xml_len = len(old_xml)
    new_xml_len = len(new_xml_bytes)

    # Tenter de padder pour garder la meme taille de segment
    if new_xml_len <= old_xml_len:
        # Ajouter des espaces de padding dans le XMP (avant le tag de fermeture)
        padding_needed = old_xml_len - new_xml_len
        # XMP standard : padding avec des espaces avant </x:xmpmeta>
        # On ajoute simplement le padding a la fin, avant la fermeture
        padded_xml = new_xml_bytes + b'\x00' * padding_needed
        new_segment_data = XMP_HEADER + padded_xml
    else:
        new_segment_data = XMP_HEADER + new_xml_bytes

    new_seg_length = len(new_segment_data) + 2  # +2 pour le champ longueur
    new_segment = struct.pack('>BB', 0xFF, 0xE1) + struct.pack('>H', new_seg_length) + new_segment_data

    return jpeg_bytes[:seg_offset] + new_segment + jpeg_bytes[seg_offset + seg_length:]


# ──────────────────────────────────────────────
#  GESTION IPTC (segment APP13)
# ──────────────────────────────────────────────

IPTC_LOCATION_RECORDS = {
    (2, 90),   # City
    (2, 92),   # Sub-location
    (2, 95),   # Province/State
    (2, 100),  # Country Code
    (2, 101),  # Country Name
}

# Records a scanner conditionnellement (supprimer seulement si contenu GPS/coord)
IPTC_CONDITIONAL_RECORDS = {
    (2, 25),   # Keywords
    (2, 105),  # Headline
}

# Patterns indicateurs de coordonnees/localisation GPS dans le texte IPTC
IPTC_GPS_PATTERNS = [
    re.compile(rb'(?i)gps'),
    re.compile(rb'(?i)latitude'),
    re.compile(rb'(?i)longitude'),
    re.compile(rb'(?i)geo[- ]?tag'),
    re.compile(rb'-?\d{1,3}\.\d{4,}'),  # decimal coordinates
]


def find_iptc_segment(jpeg_bytes):
    """
    Localise le segment APP13 (Photoshop/IPTC) dans les bytes JPEG.
    Retourne (offset, longueur) ou None.
    """
    pos = 2
    while pos < len(jpeg_bytes) - 4:
        if jpeg_bytes[pos] != 0xFF:
            break
        marker = jpeg_bytes[pos + 1]
        if marker == 0xD9 or marker == 0xDA:
            break
        seg_length = struct.unpack('>H', jpeg_bytes[pos + 2:pos + 4])[0]
        # APP13 = 0xED
        if marker == 0xED:
            return (pos, 2 + seg_length)
        pos += 2 + seg_length
    return None


def strip_iptc_location(jpeg_bytes):
    """
    Supprime les champs de localisation IPTC du segment APP13
    tout en preservant les autres champs (copyright, mots-cles, etc.).
    """
    result = find_iptc_segment(jpeg_bytes)
    if result is None:
        return jpeg_bytes

    seg_offset, seg_length = result
    seg_data = jpeg_bytes[seg_offset + 4:seg_offset + seg_length]

    # Le segment APP13 contient souvent "Photoshop 3.0\x00" suivi de ressources 8BIM
    # Les donnees IPTC sont dans le resource ID 0x0404

    # Chercher le header Photoshop
    photoshop_header = b'Photoshop 3.0\x00'
    if photoshop_header not in seg_data:
        return jpeg_bytes

    ps_start = seg_data.index(photoshop_header)
    ps_offset = ps_start + len(photoshop_header)

    new_resources = seg_data[:ps_offset]
    pos = ps_offset

    while pos < len(seg_data) - 4:
        # Chaque ressource: 8BIM (4 bytes) + resource_id (2) + pascal string + size + data
        if seg_data[pos:pos + 4] != b'8BIM':
            # Pas un marqueur 8BIM — copier le reste tel quel
            new_resources += seg_data[pos:]
            break

        resource_start = pos
        pos += 4
        if pos + 2 > len(seg_data):
            new_resources += seg_data[resource_start:]
            break

        resource_id = struct.unpack('>H', seg_data[pos:pos + 2])[0]
        pos += 2

        # Pascal string (1 byte length + string + padding to even)
        if pos >= len(seg_data):
            new_resources += seg_data[resource_start:]
            break
        pascal_len = seg_data[pos]
        pos += 1
        pos += pascal_len
        if (pascal_len + 1) % 2 != 0:
            pos += 1  # padding

        if pos + 4 > len(seg_data):
            new_resources += seg_data[resource_start:]
            break

        data_size = struct.unpack('>I', seg_data[pos:pos + 4])[0]
        pos += 4
        resource_end = pos + data_size
        if data_size % 2 != 0:
            resource_end += 1  # padding

        if resource_id == 0x0404:
            # C'est le bloc IPTC — filtrer les records de localisation
            iptc_data = seg_data[pos:pos + data_size]
            filtered_iptc = _filter_iptc_records(iptc_data)
            # Reconstruire la ressource 8BIM avec les donnees filtrees
            new_resource = b'8BIM' + struct.pack('>H', resource_id)
            new_resource += b'\x00\x00'  # pascal string vide
            new_resource += struct.pack('>I', len(filtered_iptc))
            new_resource += filtered_iptc
            if len(filtered_iptc) % 2 != 0:
                new_resource += b'\x00'
            new_resources += new_resource
        else:
            new_resources += seg_data[resource_start:resource_end]

        pos = resource_end

    # Reconstruire le segment APP13
    new_seg_length = len(new_resources) + 2
    new_segment = struct.pack('>BB', 0xFF, 0xED) + struct.pack('>H', new_seg_length) + new_resources

    return jpeg_bytes[:seg_offset] + new_segment + jpeg_bytes[seg_offset + seg_length:]


def _filter_iptc_records(iptc_data):
    """Filtre les records IPTC en supprimant ceux de localisation."""
    result = b''
    pos = 0
    while pos < len(iptc_data) - 4:
        if iptc_data[pos] != 0x1C:
            # Pas un marqueur IPTC valide
            result += iptc_data[pos:]
            break
        record_type = iptc_data[pos + 1]
        dataset_num = iptc_data[pos + 2]
        data_len = struct.unpack('>H', iptc_data[pos + 3:pos + 5])[0]
        record_end = pos + 5 + data_len

        if (record_type, dataset_num) in IPTC_LOCATION_RECORDS:
            pass  # Always strip location records
        elif (record_type, dataset_num) in IPTC_CONDITIONAL_RECORDS:
            # Only strip if content matches GPS/coordinate patterns
            record_data = iptc_data[pos + 5:record_end]
            if any(p.search(record_data) for p in IPTC_GPS_PATTERNS):
                pass  # Strip this record
            else:
                result += iptc_data[pos:record_end]
        else:
            result += iptc_data[pos:record_end]

        pos = record_end

    return result


# ──────────────────────────────────────────────
#  GESTION COM MARKERS (JPEG Comment 0xFE)
# ──────────────────────────────────────────────

# Patterns that indicate a COM segment contains location/software info
COM_SUSPICIOUS_PATTERNS = [
    re.compile(rb'(?i)gps'),
    re.compile(rb'(?i)latitude'),
    re.compile(rb'(?i)longitude'),
    re.compile(rb'(?i)location'),
    re.compile(rb'(?i)geo[- ]?tag'),
    re.compile(rb'-?\d{1,3}\.\d{4,}[, ]-?\d{1,3}\.\d{4,}'),  # coord patterns like "40.7128,-74.0060"
    re.compile(rb'(?i)photoshop'),
    re.compile(rb'(?i)lightroom'),
    re.compile(rb'(?i)gimp'),
]


def strip_suspicious_com_segments(jpeg_bytes):
    """
    Scan JPEG COM markers (0xFE). If the content matches suspicious
    patterns (GPS, location, editing software), remove the segment.
    Otherwise, leave it intact.
    """
    result = bytearray()
    pos = 0

    # Copy SOI
    if len(jpeg_bytes) < 2 or jpeg_bytes[:2] != b'\xFF\xD8':
        return jpeg_bytes
    result.extend(jpeg_bytes[:2])
    pos = 2

    while pos < len(jpeg_bytes) - 1:
        if jpeg_bytes[pos] != 0xFF:
            # Reached image data or corrupted — copy rest
            result.extend(jpeg_bytes[pos:])
            break

        marker = jpeg_bytes[pos + 1]

        # SOS (0xDA) or EOI (0xD9) — copy the rest verbatim
        if marker == 0xDA or marker == 0xD9:
            result.extend(jpeg_bytes[pos:])
            break

        # Read segment length
        if pos + 4 > len(jpeg_bytes):
            result.extend(jpeg_bytes[pos:])
            break

        seg_length = struct.unpack('>H', jpeg_bytes[pos + 2:pos + 4])[0]
        seg_total = 2 + seg_length  # marker(2) + length field is included in seg_length

        if marker == 0xFE:  # COM marker
            seg_data = jpeg_bytes[pos + 4:pos + seg_total]
            is_suspicious = any(p.search(seg_data) for p in COM_SUSPICIOUS_PATTERNS)
            if is_suspicious:
                # Skip this segment entirely
                pos += seg_total
                continue

        # Keep this segment
        result.extend(jpeg_bytes[pos:pos + seg_total])
        pos += seg_total

    return bytes(result)


# ──────────────────────────────────────────────
#  GESTION MAKERNOTES
# ──────────────────────────────────────────────

def handle_maker_notes(exif_dict):
    """
    Verifie si les MakerNotes contiennent des donnees GPS.
    Si oui, les supprime entierement. Sinon, les laisse intactes.
    """
    exif_ifd = exif_dict.get("Exif", {})
    maker_note_tag = 0x927C  # MakerNote

    if maker_note_tag not in exif_ifd:
        return False

    maker_data = exif_ifd[maker_note_tag]
    if not isinstance(maker_data, bytes):
        return False

    # Patterns indicateurs de donnees GPS dans les MakerNotes
    gps_patterns = [b'GPS', b'gps', b'Latitude', b'Longitude', b'latitude', b'longitude']
    has_gps = any(pattern in maker_data for pattern in gps_patterns)

    if has_gps:
        del exif_ifd[maker_note_tag]
        return True

    return False


# ──────────────────────────────────────────────
#  FONCTIONS DE COHERENCE
# ──────────────────────────────────────────────

def synchronize_thumbnail_ifd(exif_dict, date_str):
    """
    Synchronise le 1st IFD (thumbnail) : met a jour DateTime,
    supprime Software.
    """
    first_ifd = exif_dict.get("1st", {})
    if not first_ifd:
        return

    # Synchroniser DateTime du thumbnail
    if piexif.ImageIFD.DateTime in first_ifd:
        first_ifd[piexif.ImageIFD.DateTime] = date_str

    # Supprimer Software du thumbnail
    if piexif.ImageIFD.Software in first_ifd:
        del first_ifd[piexif.ImageIFD.Software]

    # Supprimer ProcessingSoftware du thumbnail
    for tag_to_clean in [0x000B, 0x00C6, 0x00C7]:
        if tag_to_clean in first_ifd:
            del first_ifd[tag_to_clean]


def clean_software_tags(exif_dict):
    """Supprime tous les tags Software et ProcessingSoftware de tous les IFDs."""
    for ifd_name in ["0th", "1st"]:
        ifd = exif_dict.get(ifd_name, {})
        if piexif.ImageIFD.Software in ifd:
            del ifd[piexif.ImageIFD.Software]
        for tag_to_clean in [0x000B, 0x00C6, 0x00C7]:
            if tag_to_clean in ifd:
                del ifd[tag_to_clean]


def write_offset_times(exif_dict, offset_str):
    """Ecrit les tags OffsetTime dans l'IFD Exif."""
    offset_bytes = offset_str.encode('ascii')
    exif_ifd = exif_dict.get("Exif", {})
    exif_ifd[36880] = offset_bytes  # OffsetTime
    exif_ifd[36881] = offset_bytes  # OffsetTimeOriginal
    exif_ifd[36882] = offset_bytes  # OffsetTimeDigitized


def handle_gps_extra_fields(gps_ifd, original_gps):
    """
    Preserve GPSMapDatum, GPSProcessingMethod, et les champs de mouvement
    s'ils existaient dans l'original. Ne les ajoute jamais s'ils n'existaient pas.
    """
    # GPSMapDatum (tag 18)
    if piexif.GPSIFD.GPSMapDatum in original_gps:
        gps_ifd[piexif.GPSIFD.GPSMapDatum] = original_gps[piexif.GPSIFD.GPSMapDatum]

    # GPSProcessingMethod (tag 27)
    if piexif.GPSIFD.GPSProcessingMethod in original_gps:
        gps_ifd[piexif.GPSIFD.GPSProcessingMethod] = original_gps[piexif.GPSIFD.GPSProcessingMethod]

    # GPSHPositioningError (tag 31) — iPhones write this
    GPS_H_POSITIONING_ERROR = 31
    if GPS_H_POSITIONING_ERROR in original_gps:
        gps_ifd[GPS_H_POSITIONING_ERROR] = original_gps[GPS_H_POSITIONING_ERROR]

    # Champs de mouvement/direction — preserver si presents
    motion_tags = [
        piexif.GPSIFD.GPSSpeed,
        piexif.GPSIFD.GPSSpeedRef,
        piexif.GPSIFD.GPSTrack,
        piexif.GPSIFD.GPSTrackRef,
        piexif.GPSIFD.GPSImgDirection,
        piexif.GPSIFD.GPSImgDirectionRef,
        piexif.GPSIFD.GPSDestBearing,
        piexif.GPSIFD.GPSDestBearingRef,
    ]
    for tag in motion_tags:
        if tag in original_gps:
            # Conserver la valeur originale (ou mettre speed a 0)
            if tag == piexif.GPSIFD.GPSSpeed:
                # Mettre la vitesse a 0 (photo prise a l'arret est plus coherent)
                denom = original_gps[tag][1] if isinstance(original_gps[tag], tuple) else 1
                gps_ifd[tag] = (0, denom)
            else:
                gps_ifd[tag] = original_gps[tag]


# ──────────────────────────────────────────────
#  FONCTION PRINCIPALE
# ──────────────────────────────────────────────

def modify_geolocation(input_path, latitude, longitude, altitude=None, output_path=None, date_shift_hours=None):
    """
    Modifie la geolocalisation d'une photo JPEG de maniere propre.
    Travaille directement sur les bytes JPEG — aucun re-encodage.
    """
    if output_path is None:
        output_path = input_path

    # ── Etape 1 : Lire les bytes bruts du JPEG ──
    print(f"  Lecture de : {input_path}")

    with open(input_path, 'rb') as f:
        jpeg_bytes = f.read()

    # Verifier que c'est bien un JPEG
    if jpeg_bytes[:2] != b'\xFF\xD8':
        raise ValueError(f"{input_path} n'est pas un fichier JPEG valide")

    # ── Etape 2 : Charger l'EXIF ──
    try:
        exif_dict = piexif.load(jpeg_bytes)
    except Exception:
        print(f"  Pas de donnees EXIF trouvees, on en cree de nouvelles")
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    # ── Etape 3 : Snapshot du GPS original ──
    original_gps = dict(exif_dict.get("GPS", {}))

    # ── Etape 4 : Detecter make/modele ──
    camera_make = get_camera_make(exif_dict)
    print(f"  Appareil detecte : {camera_make.decode('ascii', errors='replace') if camera_make else 'inconnu'}")

    # ── Etape 5 : Determiner la precision GPS ──
    original_denom = get_original_gps_precision(exif_dict)
    if original_denom:
        seconds_denom = original_denom
    else:
        seconds_denom = get_gps_denom_for_camera(camera_make)
    print(f"  Precision GPS (denominateur) : {seconds_denom}")

    # ── Etape 6 : Modifier les coordonnees GPS ──
    print(f"  Nouvelles coordonnees : {latitude}, {longitude}")

    lat_dms, lat_is_south = decimal_to_dms(latitude, seconds_denom)
    lon_dms, lon_is_west = decimal_to_dms(longitude, seconds_denom)

    gps_ifd = exif_dict.get("GPS", {})

    # GPSVersionID: preserver l'original si present, sinon adapter au make
    orig_version = original_gps.get(piexif.GPSIFD.GPSVersionID)
    if orig_version:
        gps_ifd[piexif.GPSIFD.GPSVersionID] = orig_version
    else:
        gps_ifd[piexif.GPSIFD.GPSVersionID] = get_gps_version_for_camera(camera_make)
    gps_ifd[piexif.GPSIFD.GPSLatitude] = lat_dms
    gps_ifd[piexif.GPSIFD.GPSLatitudeRef] = b'S' if lat_is_south else b'N'
    gps_ifd[piexif.GPSIFD.GPSLongitude] = lon_dms
    gps_ifd[piexif.GPSIFD.GPSLongitudeRef] = b'W' if lon_is_west else b'E'

    # ── Altitude ──
    alt = get_realistic_altitude(latitude, longitude, altitude)
    # Preserver le denominateur d'altitude original si disponible
    orig_alt = original_gps.get(piexif.GPSIFD.GPSAltitude)
    alt_denom = orig_alt[1] if orig_alt and isinstance(orig_alt, tuple) else get_gps_denom_for_camera(camera_make)
    gps_ifd[piexif.GPSIFD.GPSAltitude] = (int(alt * alt_denom), alt_denom)
    gps_ifd[piexif.GPSIFD.GPSAltitudeRef] = 0
    print(f"  Altitude : {alt}m")

    # ── Etape 7 : Timezone et dates ──
    tz_name = get_timezone_for_coords(latitude, longitude)
    tz = pytz.timezone(tz_name)
    print(f"  Fuseau horaire : {tz_name}")

    original_datetime_str = exif_dict.get("Exif", {}).get(
        piexif.ExifIFD.DateTimeOriginal, None
    )

    if original_datetime_str:
        if isinstance(original_datetime_str, bytes):
            original_datetime_str = original_datetime_str.decode('ascii')
        try:
            dt = datetime.strptime(original_datetime_str, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            dt = datetime.now()
    else:
        dt = datetime.now()

    if date_shift_hours is not None:
        dt = dt + timedelta(hours=date_shift_hours)
        print(f"  Date decalee de {date_shift_hours}h")

    date_str = dt.strftime("%Y:%m:%d %H:%M:%S").encode('ascii')

    exif_dict["0th"][piexif.ImageIFD.DateTime] = date_str
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = date_str
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = date_str

    localized_dt = tz.localize(dt)
    utc_offset = localized_dt.strftime('%z')
    offset_str = f"{utc_offset[:3]}:{utc_offset[3:]}"

    # ── Etape 8 : OffsetTime ──
    write_offset_times(exif_dict, offset_str)

    # ── Etape 9 : SubSecTime ──
    exif_ifd = exif_dict.get("Exif", {})
    subsec_tags = [
        piexif.ExifIFD.SubSecTime,
        piexif.ExifIFD.SubSecTimeOriginal,
        piexif.ExifIFD.SubSecTimeDigitized,
    ]
    for tag in subsec_tags:
        original_val = exif_ifd.get(tag)
        if original_val is not None:
            new_val = generate_subsec_time(original_val)
            if new_val is not None:
                exif_ifd[tag] = new_val

    # ── Etape 10 : GPS Timestamp ──
    utc_dt = localized_dt.astimezone(pytz.UTC)
    # Preserver le denominateur des secondes GPS original si disponible
    orig_ts = original_gps.get(piexif.GPSIFD.GPSTimeStamp)
    sec_denom = 1
    if orig_ts and len(orig_ts) >= 3 and isinstance(orig_ts[2], tuple) and len(orig_ts[2]) == 2:
        sec_denom = orig_ts[2][1] if orig_ts[2][1] > 0 else 1
    gps_ifd[piexif.GPSIFD.GPSTimeStamp] = (
        (utc_dt.hour, 1),
        (utc_dt.minute, 1),
        (utc_dt.second * sec_denom, sec_denom)
    )
    gps_ifd[piexif.GPSIFD.GPSDateStamp] = utc_dt.strftime("%Y:%m:%d").encode('ascii')

    # ── Etape 11 : GPSMeasureMode adaptatif ──
    if piexif.GPSIFD.GPSMeasureMode in original_gps:
        gps_ifd[piexif.GPSIFD.GPSMeasureMode] = original_gps[piexif.GPSIFD.GPSMeasureMode]
    else:
        gps_ifd[piexif.GPSIFD.GPSMeasureMode] = b'3'

    # ── Etape 12 : DOP realiste ──
    original_dop = original_gps.get(piexif.GPSIFD.GPSDOP)
    gps_ifd[piexif.GPSIFD.GPSDOP] = generate_realistic_dop(original_dop)

    # ── Etape 13 : Champs GPS supplementaires ──
    handle_gps_extra_fields(gps_ifd, original_gps)

    exif_dict["GPS"] = gps_ifd

    # ── Etape 14 : Nettoyer Software ──
    print("  Nettoyage des traces...")
    clean_software_tags(exif_dict)

    # ── Etape 15 : Synchroniser thumbnail IFD ──
    synchronize_thumbnail_ifd(exif_dict, date_str)

    # ── Etape 16 : MakerNotes ──
    maker_removed = handle_maker_notes(exif_dict)
    if maker_removed:
        print("  MakerNotes GPS detectes et supprimes")

    # ── Etape 17 : Generer et injecter l'EXIF ──
    try:
        exif_bytes = piexif.dump(exif_dict)
    except Exception:
        print(f"  Nettoyage de donnees EXIF problematiques...")
        for ifd_name in ["0th", "Exif", "1st"]:
            ifd = exif_dict.get(ifd_name, {})
            keys_to_remove = []
            for key in ifd:
                try:
                    test_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                    test_dict[ifd_name][key] = ifd[key]
                    piexif.dump(test_dict)
                except Exception:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                del ifd[key]
        exif_bytes = piexif.dump(exif_dict)

    # Injecter l'EXIF dans les bytes JPEG sans re-encoder
    exif_buf = io.BytesIO()
    piexif.insert(exif_bytes, jpeg_bytes, exif_buf)
    jpeg_bytes = exif_buf.getvalue()

    # ── Etape 18 : Modifier XMP ──
    xmp_result = find_xmp_segment(jpeg_bytes)
    if xmp_result:
        _, _, xml_data = xmp_result
        new_xml = modify_xmp_gps(xml_data, latitude, longitude, alt, utc_dt,
                                  local_dt_str=date_str.decode('ascii'), offset_str=offset_str)
        jpeg_bytes = replace_xmp_segment(jpeg_bytes, new_xml)
        print("  XMP GPS modifie")
    else:
        print("  Pas de segment XMP detecte")

    # ── Etape 18b : Nettoyer XMP etendu ──
    jpeg_bytes = clean_extended_xmp_gps(jpeg_bytes)

    # ── Etape 19 : Supprimer localisation IPTC ──
    iptc_result = find_iptc_segment(jpeg_bytes)
    if iptc_result:
        jpeg_bytes = strip_iptc_location(jpeg_bytes)
        print("  IPTC location nettoyee")
    else:
        print("  Pas de segment IPTC detecte")

    # ── Etape 20 : Supprimer COM markers suspects ──
    jpeg_bytes = strip_suspicious_com_segments(jpeg_bytes)

    # ── Etape 21 : Ecrire le fichier final ──
    # Save original timestamps BEFORE writing (for overwrite mode)
    original_stat = os.stat(input_path) if output_path == input_path else None

    print(f"  Sauvegarde : {output_path}")
    with open(output_path, 'wb') as f:
        f.write(jpeg_bytes)

    # Restaurer les timestamps du fichier
    if original_stat:
        # Overwrite mode: restore original timestamps
        os.utime(output_path, (original_stat.st_atime, original_stat.st_mtime))
        if sys.platform == 'win32':
            set_file_creation_time(output_path, original_stat.st_ctime)
    elif output_path != input_path and os.path.exists(input_path):
        preserve_file_timestamps(input_path, output_path)

    print("")
    print("  Termine ! Resume des modifications :")
    print(f"   GPS      : {latitude}, {longitude}")
    print(f"   Altitude : {alt}m")
    print(f"   Timezone : {tz_name} ({offset_str})")
    print(f"   Date     : {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Fichier  : {output_path}")

    return output_path


def verify_result(file_path):
    """
    Verifie le resultat en affichant les metadonnees GPS du fichier modifie.
    Verifie aussi la coherence XMP et IPTC.
    """
    print("\n  Verification du fichier modifie :")
    print("-" * 50)

    with open(file_path, 'rb') as f:
        jpeg_bytes = f.read()

    exif_dict = piexif.load(jpeg_bytes)
    gps = exif_dict.get("GPS", {})

    if not gps:
        print("   Aucune donnee GPS trouvee !")
        return

    # Latitude
    if piexif.GPSIFD.GPSLatitude in gps:
        lat = gps[piexif.GPSIFD.GPSLatitude]
        lat_ref = gps.get(piexif.GPSIFD.GPSLatitudeRef, b'N')
        lat_dec = lat[0][0]/lat[0][1] + lat[1][0]/lat[1][1]/60 + lat[2][0]/lat[2][1]/3600
        if lat_ref == b'S':
            lat_dec = -lat_dec
        print(f"   Latitude  : {lat_dec:.6f} ({lat_ref.decode()})")

    # Longitude
    if piexif.GPSIFD.GPSLongitude in gps:
        lon = gps[piexif.GPSIFD.GPSLongitude]
        lon_ref = gps.get(piexif.GPSIFD.GPSLongitudeRef, b'E')
        lon_dec = lon[0][0]/lon[0][1] + lon[1][0]/lon[1][1]/60 + lon[2][0]/lon[2][1]/3600
        if lon_ref == b'W':
            lon_dec = -lon_dec
        print(f"   Longitude : {lon_dec:.6f} ({lon_ref.decode()})")

    # Altitude
    if piexif.GPSIFD.GPSAltitude in gps:
        alt = gps[piexif.GPSIFD.GPSAltitude]
        print(f"   Altitude  : {alt[0]/alt[1]:.1f}m")

    # Date GPS
    if piexif.GPSIFD.GPSDateStamp in gps:
        print(f"   Date GPS  : {gps[piexif.GPSIFD.GPSDateStamp].decode()}")

    # Date EXIF
    exif_data = exif_dict.get("Exif", {})
    if piexif.ExifIFD.DateTimeOriginal in exif_data:
        dto = exif_data[piexif.ExifIFD.DateTimeOriginal]
        if isinstance(dto, bytes):
            dto = dto.decode()
        print(f"   Date EXIF : {dto}")

    # OffsetTime
    if 36880 in exif_data:
        ot = exif_data[36880]
        if isinstance(ot, bytes):
            ot = ot.decode()
        print(f"   OffsetTime: {ot}")
    else:
        print(f"   OffsetTime: MANQUANT")

    # SubSecTime
    if piexif.ExifIFD.SubSecTimeOriginal in exif_data:
        sst = exif_data[piexif.ExifIFD.SubSecTimeOriginal]
        if isinstance(sst, bytes):
            sst = sst.decode()
        print(f"   SubSecTime: {sst}")

    # Software
    if piexif.ImageIFD.Software in exif_dict.get("0th", {}):
        print(f"   ALERTE Software present : {exif_dict['0th'][piexif.ImageIFD.Software]}")
    else:
        print(f"   OK Pas de champ Software")

    # Software dans 1st IFD
    if piexif.ImageIFD.Software in exif_dict.get("1st", {}):
        print(f"   ALERTE Software dans thumbnail IFD")
    else:
        print(f"   OK Thumbnail IFD propre")

    # MakerNotes
    if 0x927C in exif_data:
        maker_data = exif_data[0x927C]
        if isinstance(maker_data, bytes) and any(p in maker_data for p in [b'GPS', b'gps', b'Latitude']):
            print(f"   ALERTE MakerNotes contient du GPS")
        else:
            print(f"   OK MakerNotes sans GPS")
    else:
        print(f"   OK Pas de MakerNotes")

    # Thumbnail
    if exif_dict.get("thumbnail"):
        print(f"   OK Thumbnail EXIF present")
    else:
        print(f"   INFO Pas de thumbnail EXIF")

    # GPS Precision
    if piexif.GPSIFD.GPSLatitude in gps:
        denom = gps[piexif.GPSIFD.GPSLatitude][2][1]
        print(f"   Precision GPS denom: {denom}")

    # DOP
    if piexif.GPSIFD.GPSDOP in gps:
        dop = gps[piexif.GPSIFD.GPSDOP]
        print(f"   DOP: {dop[0]/dop[1]:.1f}")

    # MeasureMode
    if piexif.GPSIFD.GPSMeasureMode in gps:
        mode = gps[piexif.GPSIFD.GPSMeasureMode]
        if isinstance(mode, bytes):
            mode = mode.decode()
        print(f"   MeasureMode: {mode}")

    # Verifier XMP
    xmp_result = find_xmp_segment(jpeg_bytes)
    if xmp_result:
        _, _, xml_data = xmp_result
        xml_str = xml_data.decode('utf-8', errors='replace')
        # Chercher des coordonnees GPS dans le XMP
        lat_match = re.search(r'exif:GPSLatitude[=">]([^"<]+)', xml_str)
        lon_match = re.search(r'exif:GPSLongitude[=">]([^"<]+)', xml_str)
        if lat_match:
            print(f"   XMP Lat: {lat_match.group(1)}")
        if lon_match:
            print(f"   XMP Lon: {lon_match.group(1)}")

        # Verifier absence de localisation
        location_tags = ['photoshop:City', 'photoshop:State', 'photoshop:Country',
                        'Iptc4xmpCore:Location']
        for tag in location_tags:
            if tag in xml_str:
                print(f"   ALERTE {tag} encore present dans XMP")
        if not any(tag in xml_str for tag in location_tags):
            print(f"   OK Pas de localisation textuelle dans XMP")
    else:
        print(f"   INFO Pas de segment XMP")

    # Verifier IPTC
    iptc_result = find_iptc_segment(jpeg_bytes)
    if iptc_result:
        print(f"   INFO Segment IPTC present (localisation nettoyee)")
    else:
        print(f"   INFO Pas de segment IPTC")

    print("-" * 50)


# ──────────────────────────────────────────────
#  GEOCODAGE — Mode Adresse
# ──────────────────────────────────────────────

def geocode_address(address_string):
    """
    Geocode une adresse postale en coordonnees (lat, lon).
    Utilise Nominatim (gratuit, pas d'API key).
    """
    try:
        from geopy.geocoders import Nominatim
    except ImportError:
        print("  ERREUR : le module 'geopy' est requis pour le mode adresse.")
        print("  Installez-le avec : python -m pip install geopy")
        sys.exit(1)

    geolocator = Nominatim(user_agent="geo_modifier_tool")
    location = geolocator.geocode(address_string)

    if location is None:
        print(f"  ERREUR : adresse introuvable : {address_string}")
        sys.exit(1)

    print(f"  Adresse resolue : {location.address}")
    print(f"  Coordonnees     : {location.latitude}, {location.longitude}")
    return (location.latitude, location.longitude)


# ──────────────────────────────────────────────
#  POINT D'ENTREE
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Modifie la geolocalisation d'une photo JPEG proprement",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python geo.py photo.jpg 48.8566 2.3522                            # lat/lon
  python geo.py photo.jpg --address "12 rue de Rivoli, 75001 Paris" # adresse
  python geo.py photo.jpg "Tour Eiffel, Paris"                      # positionnel
  python geo.py photo.jpg 48.8566 2.3522 -a 35                      # avec altitude
  python geo.py photo.jpg 48.8566 2.3522 -o out.jpg                 # fichier separe
        """
    )

    parser.add_argument("photo", help="Chemin vers la photo JPEG")
    parser.add_argument("coords", nargs='*', help="lat lon OU adresse entre guillemets")
    parser.add_argument("--address", "-addr", default=None,
                       help="Adresse postale (ex: '12 rue de Rivoli, 75001 Paris')")
    parser.add_argument("-a", "--altitude", type=float, default=None,
                       help="Altitude en metres (auto-estime si non specifie)")
    parser.add_argument("-o", "--output", default=None,
                       help="Fichier de sortie (ecrase l'original si non specifie)")
    parser.add_argument("--date-shift", type=float, default=None,
                       help="Decalage horaire en heures (ex: -2 pour reculer de 2h)")
    parser.add_argument("--verify", action="store_true", default=True,
                       help="Verifier le resultat apres modification")

    args = parser.parse_args()

    if not os.path.exists(args.photo):
        print(f"  Fichier introuvable : {args.photo}")
        sys.exit(1)

    # Determiner lat/lon selon le mode d'entree
    if args.address:
        # Mode --address explicite
        latitude, longitude = geocode_address(args.address)
    elif args.coords and len(args.coords) == 2:
        # Tenter de parser comme lat/lon numeriques
        try:
            latitude = float(args.coords[0])
            longitude = float(args.coords[1])
        except ValueError:
            # Pas numeriques — joindre en adresse
            address_str = ' '.join(args.coords)
            latitude, longitude = geocode_address(address_str)
    elif args.coords and len(args.coords) >= 1:
        # Plusieurs mots ou une adresse entre guillemets
        address_str = ' '.join(args.coords)
        # Verifier si c'est une adresse (contient des non-chiffres)
        try:
            if len(args.coords) == 1:
                # Pourrait etre un seul nombre (erreur) ou une adresse
                float(args.coords[0])
                print("  ERREUR : specifiez latitude ET longitude, ou utilisez --address")
                sys.exit(1)
        except ValueError:
            pass  # C'est une adresse
        latitude, longitude = geocode_address(address_str)
    else:
        print("  ERREUR : specifiez des coordonnees (lat lon) ou une adresse.")
        print("  Exemples :")
        print('    python geo.py photo.jpg 48.8566 2.3522')
        print('    python geo.py photo.jpg --address "12 rue de Rivoli, Paris"')
        print('    python geo.py photo.jpg "Tour Eiffel, Paris"')
        sys.exit(1)

    result_path = modify_geolocation(
        input_path=args.photo,
        latitude=latitude,
        longitude=longitude,
        altitude=args.altitude,
        output_path=args.output,
        date_shift_hours=args.date_shift,
    )

    if args.verify:
        verify_result(result_path)

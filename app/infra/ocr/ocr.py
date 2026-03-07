#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Улучшенное OCR-распознавание кассового чека на Python.

Что делает программа:
1. Загружает фото чека с диска
2. Находит и выравнивает область чека
3. Создает несколько вариантов предобработки изображения
4. Прогоняет OCR по нескольким стратегиям
5. Извлекает:
   - название магазина
   - адрес
   - дату/время
   - список товаров
6. Фильтрует служебные строки
7. Исправляет типовые OCR-ошибки
8. Проверяет согласованность с итогом чека
9. Сохраняет товары в CSV
10. Показывает оценку качества результата

Зависимости:
    pip install pytesseract pillow opencv-python numpy

Также нужен установленный Tesseract OCR:
- Linux:
    sudo apt-get install tesseract-ocr tesseract-ocr-rus
- macOS:
    brew install tesseract
- Windows:
    установить Tesseract OCR и при необходимости прописать путь
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image


# ------------------------------------------------------------
# При необходимости укажите путь к tesseract.exe на Windows
# ------------------------------------------------------------
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA_DIR = r"C:\Program Files\Tesseract-OCR\tessdata"

# ============================================================
# Модели данных
# ============================================================

@dataclass
class Product:
    """Одна товарная позиция."""
    name: str
    quantity: float
    price: float
    line_total: Optional[float] = None
    confidence: float = 0.0


@dataclass
class ReceiptMeta:
    """Основные реквизиты чека."""
    store_name: Optional[str] = None
    store_address: Optional[str] = None
    receipt_date: Optional[str] = None
    total: Optional[float] = None
    subtotal: Optional[float] = None


@dataclass
class OCRCandidate:
    """Один результат OCR для одной стратегии."""
    label: str
    raw_text: str
    lines: List[str]


@dataclass
class ReceiptResult:
    """Итоговое распознанное содержимое чека."""
    meta: ReceiptMeta = field(default_factory=ReceiptMeta)
    products: List[Product] = field(default_factory=list)
    raw_ocr_variants: List[OCRCandidate] = field(default_factory=list)
    best_raw_text: str = ""
    score: float = 0.0
    quality_label: str = "низкое"


# ============================================================
# Константы и словари
# ============================================================

MONEY_RE = r"\d+[.,]\d{2}"
QTY_RE = r"\d+(?:[.,]\d+)?"

SERVICE_KEYWORDS = [
    "скидка", "подытог", "итог", "округление", "наличными", "электронными",
    "сдача", "принято", "ндс", "сумма ндс", "сайт фнс", "рн ккт", "место расчетов",
    "кассир", "касса", "смена", "чек", "приход", "инн", "сно", "код", "ооо",
    "fn", "fd", "fp", "qr", "ккт", "фнс"
]

HEADER_NOISE_KEYWORDS = [
    "кассовый чек", "товарный чек", "receipt", "чек", "цена", "скидка",
    "цена со скидкой", "кол-во", "итого", "ндс"
]

ADDRESS_HINTS = [
    "ул", "улица", "пр-т", "просп", "проспект", "д.", "дом", "г.", "город",
    "р-н", "район", "обл", "область", "пер", "переулок", "шоссе", "корп",
    "строение", "кв", "д ", "ул. ", "г ", "street", "road", "avenue", "city"
]

STORE_NAME_DICTIONARY = [
    "Пятёрочка", "Пятерочка", "Магнит", "Лента", "Перекрёсток", "Перекресток",
    "Дикси", "Ашан", "Окей", "ОКЕЙ", "Fix Price", "Красное&Белое", "Верный"
]

COMMON_WORD_FIXES = {
    # Частые OCR-ошибки на чеках
    "76r": "76г",
    "400r": "400г",
    "600r": "600г",
    "970нл": "970мл",
    "970Hn": "970мл",
    "1,93я": "1,93л",
    "1,93л": "1,93л",
    "67Х": "67%",
    "67x": "67%",
    "РАВА": "РЯБА",
    "PABA": "РЯБА",
    "Найон": "Майон",
    "цет.": "дет.",
    "ANE.": "АПЕЛ.",
    "Ham.": "Нап.",
    "flb": "Люб.",
    "K.Ц.": "К.ц.",
    "Нол.": "Мол.",
    "КПССОБЫи": "КАССОВЫЙ",
    "НВЛИЧНЫНИ": "НАЛИЧНЫМИ",
    "CKHAKA": "СКИДКА",
    "NOMIOF": "ПОДЫТОГ",
}

PRODUCT_HINTS = [
    "мол", "батончик", "майон", "томат", "напит", "ябл", "вишн", "чер", "апел",
    "манго", "дет", "мяк", "picnic", "ряба", "сливовидный"
]


# ============================================================
# Вспомогательные функции
# ============================================================

def normalize_spaces(text: str) -> str:
    """Нормализация пробелов и переносов."""
    text = text.replace("\xa0", " ")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_line(line: str) -> str:
    """Очистка одной строки."""
    line = line.replace("|", " ")
    line = line.replace("_", " ")
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    return line


def parse_decimal(value: str) -> Optional[float]:
    """Преобразование строки числа в float."""
    try:
        return float(value.replace(",", ".").strip())
    except Exception:
        return None


def money_values_from_line(line: str) -> List[float]:
    """Извлечение всех денежных значений из строки."""
    values = []
    for m in re.findall(MONEY_RE, line):
        v = parse_decimal(m)
        if v is not None:
            values.append(v)
    return values


def looks_like_service_line(line: str) -> bool:
    """Проверка, является ли строка служебной."""
    lower = line.lower()
    return any(word in lower for word in SERVICE_KEYWORDS)


def looks_like_header_noise(line: str) -> bool:
    """Проверка, является ли строка заголовком/шумом."""
    lower = line.lower()
    return any(word in lower for word in HEADER_NOISE_KEYWORDS)


def looks_like_product_name(line: str) -> bool:
    """Проверка, похожа ли строка на название товара."""
    lower = line.lower()

    if looks_like_service_line(line) or looks_like_header_noise(line):
        return False

    if len(line) < 4:
        return False

    has_letters = bool(re.search(r"[A-Za-zА-Яа-яЁё]", line))
    if not has_letters:
        return False

    # Название товара часто начинается с кода, который допустим
    # Но полностью служебные строки исключаем
    return True


def is_probable_address(line: str) -> bool:
    """Эвристика для определения адресной строки."""
    lower = line.lower()
    has_digit = bool(re.search(r"\d", line))
    has_hint = any(h in lower for h in ADDRESS_HINTS)
    return has_digit and has_hint


def safe_round2(value: Optional[float]) -> Optional[float]:
    """Округление до 2 знаков."""
    if value is None:
        return None
    return round(value + 1e-9, 2)


def order_points(pts: np.ndarray) -> np.ndarray:
    """Упорядочивание 4 точек прямоугольника."""
    rect = np.zeros((4, 2), dtype="float32")

    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]   # левый верх
    rect[2] = pts[np.argmax(s)]   # правый низ

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # правый верх
    rect[3] = pts[np.argmax(diff)]  # левый низ

    return rect


# ============================================================
# Предобработка изображения
# ============================================================

def load_image_bgr(image_path: str) -> np.ndarray:
    """Загрузка изображения в формате BGR."""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Не удалось загрузить изображение: {image_path}")
    return img


def detect_receipt_contour(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    """
    Поиск крупного контура чека.
    Возвращает 4 угловые точки либо None.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    edged = cv2.Canny(blur, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edged = cv2.dilate(edged, kernel, iterations=2)
    edged = cv2.erode(edged, kernel, iterations=1)

    contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    image_area = image_bgr.shape[0] * image_bgr.shape[1]
    best_quad = None
    best_area = 0.0

    for cnt in contours:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)

        area = cv2.contourArea(cnt)
        if area < image_area * 0.08:
            continue

        if len(approx) == 4 and area > best_area:
            best_quad = approx.reshape(4, 2)
            best_area = area

    return best_quad


def perspective_warp(image_bgr: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Выравнивание чека по 4 углам."""
    rect = order_points(quad.astype(np.float32))
    (tl, tr, br, bl) = rect

    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = int(max(width_a, width_b))

    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = int(max(height_a, height_b))

    dst = np.array([
        [0, 0],
        [max_width - 1, 0],
        [max_width - 1, max_height - 1],
        [0, max_height - 1],
    ], dtype="float32")

    matrix = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image_bgr, matrix, (max_width, max_height))

    return warped


def auto_rotate_if_needed(image_bgr: np.ndarray) -> np.ndarray:
    """Поворот, чтобы чек был вертикальным."""
    h, w = image_bgr.shape[:2]
    if w > h:
        return cv2.rotate(image_bgr, cv2.ROTATE_90_CLOCKWISE)
    return image_bgr


def upscale_image(gray: np.ndarray, factor: float = 2.0) -> np.ndarray:
    """Увеличение изображения для OCR."""
    h, w = gray.shape[:2]
    return cv2.resize(gray, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_CUBIC)


def build_preprocessed_variants(image_bgr: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """
    Создание нескольких вариантов изображения.
    OCR потом будет запущен на всех.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = upscale_image(gray, factor=2.5)

    variants: List[Tuple[str, np.ndarray]] = []

    # Вариант 1: обычный grayscale
    variants.append(("gray", gray))

    # Вариант 2: median blur + adaptive threshold
    med = cv2.medianBlur(gray, 3)
    adp1 = cv2.adaptiveThreshold(
        med, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 15
    )
    variants.append(("adaptive_gaussian", adp1))

    # Вариант 3: bilateral + OTSU
    bil = cv2.bilateralFilter(gray, 7, 50, 50)
    _, otsu = cv2.threshold(bil, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu))

    # Вариант 4: CLAHE + OTSU
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    cl = clahe.apply(gray)
    _, otsu2 = cv2.threshold(cl, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("clahe_otsu", otsu2))

    # Вариант 5: инверсия при слабом контрасте
    inv = cv2.bitwise_not(otsu2)
    variants.append(("inverted", inv))

    # Вариант 6: жёсткая бинаризация
    _, binary160 = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
    variants.append(("binary160", binary160))

    # Вариант 7: жёсткая бинаризация после CLAHE
    _, binary180 = cv2.threshold(cl, 180, 255, cv2.THRESH_BINARY)
    variants.append(("clahe_binary180", binary180))

        # Вариант 8: морфологическое закрытие после OTSU
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    morph_close = cv2.morphologyEx(otsu2, cv2.MORPH_CLOSE, kernel_close)
    variants.append(("morph_close", morph_close))

    # Вариант 9: лёгкое открытие для удаления мелкого шума
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
    morph_open = cv2.morphologyEx(otsu2, cv2.MORPH_OPEN, kernel_open)
    variants.append(("morph_open", morph_open))

    # Вариант 10: bilateral + CLAHE + OTSU
    bil2 = cv2.bilateralFilter(cl, 9, 75, 75)
    _, bil2_otsu = cv2.threshold(bil2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("bilateral_clahe_otsu", bil2_otsu))

    return variants


# ============================================================
# OCR
# ============================================================

def image_to_pil(image_gray_or_bin: np.ndarray) -> Image.Image:
    """Перевод массива OpenCV в PIL.Image."""
    return Image.fromarray(image_gray_or_bin)


def run_ocr_text(image_arr: np.ndarray, lang: str, psm: int) -> str:
    """OCR обычным текстом."""
    pil = image_to_pil(image_arr)
    config = (
        f"--oem 3 "
        f"--psm {psm} "
        f'--tessdata-dir "{TESSDATA_DIR}" '
        "-c preserve_interword_spaces=1 "
    )
    return pytesseract.image_to_string(
        pil,
        lang=lang,
        config=config,
    )


def run_ocr_data(image_arr: np.ndarray, lang: str, psm: int) -> dict:
    """OCR с координатами и confidence."""
    pil = image_to_pil(image_arr)
    config = f"--oem 3 --psm {psm}"
    return pytesseract.image_to_data(
        pil, lang=lang, config=config, output_type=pytesseract.Output.DICT
    )


def split_lines(text: str) -> List[str]:
    """Разбиение OCR текста на очищенные строки."""
    lines = [clean_line(x) for x in normalize_spaces(text).splitlines()]
    return [x for x in lines if x]

def estimate_text_noise(raw_text: str) -> float:
    if not raw_text:
        return 100.0

    weird = len(re.findall(r"[^A-Za-zА-Яа-яЁё0-9\s.,:%()/№\-&\"«»\n]", raw_text))
    letters = len(re.findall(r"[A-Za-zА-Яа-яЁё]", raw_text))
    total = max(len(raw_text), 1)

    weird_ratio = weird / total
    letter_ratio = letters / total

    penalty = weird_ratio * 80

    # если слишком мало буквенного текста, это тоже подозрительно
    if letter_ratio < 0.25:
        penalty += 10

    return penalty


def collect_ocr_candidates(variants: List[Tuple[str, np.ndarray]], lang: str) -> List[OCRCandidate]:
    """
    OCR по нескольким вариантам изображения и нескольким psm.
    """
    candidates: List[OCRCandidate] = []

    # psm=6: один текстовый блок
    # psm=4: блок столбцов
    # psm=11: разреженный текст
    for label, arr in variants:
        for psm in (6, 4, 11, 12, 3):
            try:
                text = run_ocr_text(arr, lang=lang, psm=psm)
                lines = split_lines(text)
                candidates.append(OCRCandidate(
                    label=f"{label}_psm{psm}",
                    raw_text=normalize_spaces(text),
                    lines=lines
                ))
            except Exception:
                continue

    return candidates


# ============================================================
# Исправление OCR-ошибок
# ============================================================

def apply_common_text_fixes(text: str) -> str:
    """Исправление типовых OCR-ошибок по всему тексту."""
    fixed = text
    for src, dst in COMMON_WORD_FIXES.items():
        fixed = fixed.replace(src, dst)
    return fixed


def fix_product_name(name: str) -> str:
    """Исправление типовых OCR-ошибок в названии товара."""
    fixed = name

    for src, dst in COMMON_WORD_FIXES.items():
        fixed = fixed.replace(src, dst)

    # Исправления отдельных символов в контексте единиц измерения
    fixed = re.sub(r"(\d)\s*r\b", r"\1 г", fixed)
    fixed = fixed.replace("  ", " ")
    fixed = fixed.replace(" ,", ",").replace(" .", ".")
    fixed = re.sub(r"\s+", " ", fixed).strip()

    return fixed


# ============================================================
# Извлечение реквизитов
# ============================================================

def extract_store_name(lines: List[str]) -> Optional[str]:
    top_lines = lines[:10]

    # 1. Сначала пробуем словарь известных сетей
    for line in top_lines:
        l = clean_line(line)
        if not l:
            continue

        normalized = l.lower().replace("ё", "е")
        for known in STORE_NAME_DICTIONARY:
            if known.lower().replace("ё", "е") in normalized:
                return known

    candidates = []
    for line in top_lines:
        l = clean_line(line)
        if not l:
            continue

        if looks_like_header_noise(l) or looks_like_service_line(l):
            continue

        # магазин обычно не слишком длинный
        if len(l) < 4 or len(l) > 32:
            continue

        # адресные строки тут не нужны
        if is_probable_address(l):
            continue

        letters = len(re.findall(r"[A-Za-zА-Яа-яЁё]", l))
        digits = len(re.findall(r"\d", l))
        weird = len(re.findall(r"[^A-Za-zА-Яа-яЁё0-9\s&\-.\"«»]", l))

        # если букв слишком мало — это мусор
        if letters < 5:
            continue

        # слишком шумные строки не брать
        if weird > 2:
            continue

        # у названия магазина обычно букв больше, чем цифр
        score = letters * 1.2 - digits * 1.5 - weird * 2 - abs(len(l) - 12) * 0.15
        candidates.append((score, l))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    return None

def extract_date(text: str) -> Optional[str]:
    """Извлечение даты/времени чека."""
    patterns = [
        r"\b\d{2}\.\d{2}\.\d{2,4}\s+\d{2}:\d{2}(?::\d{2})?\b",
        r"\b\d{2}[./-]\d{2}[./-]\d{2,4}\s+\d{2}:\d{2}(?::\d{2})?\b",
        r"\b\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?\b",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None


def extract_total(text: str) -> Optional[float]:
    """Извлечение общего итога."""
    # Ищем именно ИТОГ, а не строку товара
    patterns = [
        r"итог[:\s]+(" + MONEY_RE + r")",
        r"подытог[:\s]+(" + MONEY_RE + r")",
    ]

    found = []
    lower = text.lower()

    for p in patterns:
        for m in re.finditer(p, lower):
            value = parse_decimal(m.group(1))
            if value is not None:
                found.append(value)

    if not found:
        return None

    # Предпочтем максимальное значение
    return max(found)


def extract_address(lines: List[str]) -> Optional[str]:
    """
    Извлечение адреса.
    Улучшено:
    - поиск в нижней части чека
    - склейка соседних строк
    """
    if not lines:
        return None

    lower_part = lines[max(0, len(lines) // 2 - 3):]

    candidates: List[str] = []

    for i, line in enumerate(lower_part):
        l1 = clean_line(line)
        if not is_probable_address(l1):
            continue

        combined = l1
        if i + 1 < len(lower_part):
            l2 = clean_line(lower_part[i + 1])
            # Если строка оборвана, пробуем склеить
            if len(l2) <= 20 and re.search(r"[А-Яа-яA-Za-z0-9]", l2):
                combined = f"{l1} {l2}".strip()

        candidates.append(combined)

    if not candidates:
        return None

    # Выбираем самый содержательный адрес
    candidates.sort(key=lambda s: (len(s), s.count(",")), reverse=True)
    best = candidates[0]

    # Небольшая нормализация
    best = best.replace("Г.", "г.")
    best = re.sub(r"\s+,", ",", best)
    best = re.sub(r"\s+", " ", best).strip()

    return best


# ============================================================
# Извлечение товарных строк
# ============================================================

def is_summary_start(line: str) -> bool:
    """Проверка, начинается ли блок итогов."""
    lower = line.lower()
    stop_words = [
        "скидка", "подытог", "итог", "округление", "наличными", "электронными",
        "сдача", "принято", "сумма ндс"
    ]
    return any(word in lower for word in stop_words)


def strip_leading_product_code(line: str) -> str:
    """Удаление ведущего кода товара."""
    line = line.strip()
    line = re.sub(r"^[*#]?\d{5,}\s+", "", line)
    return line.strip()


def extract_qty_from_pricing_line(line: str) -> Optional[float]:
    """Извлечение количества из строки цен."""
    patterns = [
        rf"(?:x|\*|\^)\s*({QTY_RE})",
        rf"\b({QTY_RE})\s*(?:x|\*|\^)",
    ]
    for p in patterns:
        m = re.search(p, line, flags=re.IGNORECASE)
        if m:
            return parse_decimal(m.group(1))

    # Для чеков часто количество просто равно 1, но не всегда явно отделено
    # Если встречается отдельная "1" между ценами
    tokens = re.findall(r"\S+", line)
    for t in tokens:
        if t in ("1", "1.0", "1,0"):
            return 1.0

    return None


def extract_price_from_pricing_line(line: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Извлечение цены и суммы строки.
    Возвращает (цена_за_единицу, итог_строки)
    """
    values = money_values_from_line(line)
    if not values:
        return None, None

    if len(values) == 1:
        return values[0], values[0]

    # Для чека логичнее брать максимальную сумму как итог строки,
    # а цену — первое адекватное значение
    price = values[0]
    line_total = max(values)

    # если итог меньше цены, значит OCR сломал строку
    if line_total < price:
        line_total = price

    return price, line_total

def product_name_score(name: str) -> float:
    """Оценка правдоподобия названия товара."""
    score = 0.0
    lower = name.lower()

    if not name:
        return -10.0

    if looks_like_service_line(name):
        score -= 10

    if re.search(r"[A-Za-zА-Яа-яЁё]", name):
        score += 2

    if len(name) >= 6:
        score += 1

    if any(h in lower for h in PRODUCT_HINTS):
        score += 3

    if re.search(r"\d+(мл|л|г|кг|%)", lower):
        score += 2

    if len(re.findall(MONEY_RE, name)) > 0:
        score -= 3

    return score


def looks_like_pricing_line(line: str) -> bool:
    """Проверка, похожа ли строка на строку цены/количества/итога."""
    if looks_like_service_line(line):
        return False

    money_count = len(re.findall(MONEY_RE, line))
    has_qty_marker = bool(re.search(r"(x|\*|\^)", line, flags=re.IGNORECASE))

    return money_count >= 1 and (has_qty_marker or money_count >= 2)


def build_products_from_lines(lines: List[str]) -> List[Product]:
    """
    Основной разбор товаров.
    Улучшено:
    - двухстрочный формат
    - фильтрация служебных строк
    - поддержка товаров с одной строкой цены
    - не продолжает парсить после начала блока итогов
    """
    products: List[Product] = []
    i = 0
    in_summary_block = False

    while i < len(lines):
        line = clean_line(lines[i])

        if not line:
            i += 1
            continue

        if is_summary_start(line):
            in_summary_block = True

        if in_summary_block:
            i += 1
            continue

        if looks_like_service_line(line) or looks_like_header_noise(line):
            i += 1
            continue

        # ----------------------------
        # Сценарий 1: двухстрочный товар
        # ----------------------------
        if looks_like_product_name(line) and i + 1 < len(lines):
            next_line = clean_line(lines[i + 1])

            if looks_like_pricing_line(next_line):
                name = strip_leading_product_code(line)
                name = fix_product_name(name)

                qty = extract_qty_from_pricing_line(next_line)
                if qty is None:
                    qty = 1.0

                price, line_total = extract_price_from_pricing_line(next_line)

                if price is not None and product_name_score(name) >= 3:
                    confidence = 0.55
                    if any(h in name.lower() for h in PRODUCT_HINTS):
                        confidence += 0.15
                    if qty is not None:
                        confidence += 0.10
                    if line_total is not None:
                        confidence += 0.10

                    products.append(Product(
                        name=name,
                        quantity=qty,
                        price=price,
                        line_total=line_total,
                        confidence=min(confidence, 1.0)
                    ))
                    i += 2
                    continue

        # ----------------------------
        # Сценарий 2: товар в одной строке
        # ----------------------------
        # Пример:
        # "Товар 1 49.99"
        m_single = re.match(
            rf"^(.*?[A-Za-zА-Яа-яЁё].*?)\s+({QTY_RE})\s+({MONEY_RE})$",
            line
        )
        if m_single and not looks_like_service_line(line):
            name = fix_product_name(strip_leading_product_code(m_single.group(1)))
            qty = parse_decimal(m_single.group(2)) or 1.0
            price = parse_decimal(m_single.group(3))
            if price is not None and product_name_score(name) >= 3:
                products.append(Product(
                    name=name,
                    quantity=qty,
                    price=price,
                    line_total=safe_round2(qty * price),
                    confidence=0.50
                ))
                i += 1
                continue

        # ----------------------------
        # Сценарий 3: строка с названием и ценой в конце
        # ----------------------------
        m_price_end = re.match(
            rf"^(.*?[A-Za-zА-Яа-яЁё].*?)\s+({MONEY_RE})$",
            line
        )
        if m_price_end and not looks_like_service_line(line):
            name = fix_product_name(strip_leading_product_code(m_price_end.group(1)))
            price = parse_decimal(m_price_end.group(2))
            if price is not None and product_name_score(name) >= 3:
                products.append(Product(
                    name=name,
                    quantity=1.0,
                    price=price,
                    line_total=price,
                    confidence=0.40
                ))
                i += 1
                continue

        i += 1

    return postprocess_products(products)


def postprocess_products(products: List[Product]) -> List[Product]:
    """
    Постобработка товаров:
    - чистка названий
    - удаление служебных строк
    - удаление слишком слабых кандидатов
    """
    cleaned: List[Product] = []

    for p in products:
        name = clean_line(p.name)
        name = fix_product_name(name)

        if not name:
            continue

        if looks_like_service_line(name) or looks_like_header_noise(name):
            continue

        if product_name_score(name) <= 0:
            continue

        # Фильтр на явно неверные цены
        if p.price <= 0 or p.price > 100000:
            continue

        # Фильтр количества
        if p.quantity <= 0 or p.quantity > 1000:
            continue
        letters = len(re.findall(r"[A-Za-zА-Яа-яЁё]", name))
        weird = len(re.findall(r"[^A-Za-zА-Яа-яЁё0-9\s.,:%()/№\-]", name))

        if letters < 4:
            continue

        if weird > 3:
            continue

        if len(re.findall(r"\b[A-Za-zА-Яа-яЁё]\b", name)) >= 3:
            continue

        alnum = len(re.findall(r"[A-Za-zА-Яа-яЁё0-9]", name))
        if alnum / max(len(name), 1) < 0.55:
            continue

        if re.search(r"[A-Za-zА-Яа-яЁё]{1}\s+[A-Za-zА-Яа-яЁё]{1}\s+[A-Za-zА-Яа-яЁё]{1}", name):
            continue

        cleaned.append(Product(
            name=name,
            quantity=p.quantity,
            price=safe_round2(p.price) or p.price,
            line_total=safe_round2(p.line_total),
            confidence=p.confidence
        ))

    return cleaned


# ============================================================
# Анализ OCR-кандидатов и выбор лучшего результата
# ============================================================

def score_candidate(lines: List[str], raw_text: str, meta: ReceiptMeta, products: List[Product]) -> float:
    """
    Оценка качества OCR-кандидата.
    Чем больше итоговый score, тем лучше вариант.
    """
    score = 0.0

    # Название магазина
    if meta.store_name:
        score += 15
        if meta.store_name in STORE_NAME_DICTIONARY:
            score += 8

    # Адрес
    if meta.store_address:
        score += 14
        if re.search(r"\d", meta.store_address):
            score += 2
        if "," in meta.store_address:
            score += 2

    # Дата
    if meta.receipt_date:
        score += 12

    # Итог
    if meta.total is not None:
        score += 8

    # Товары
    score += min(len(products) * 4, 40)

    # Бонус за содержательные названия
    for p in products[:12]:
        score += min(product_name_score(p.name), 4)

    # Штраф за мусор вверху
    if lines:
        first = lines[0]
        weird = len(re.findall(r"[^\w\sА-Яа-яЁё&\-.]", first))
        score -= weird * 1.5

    # Штраф за служебные слова, попавшие в товары
    for p in products:
        if looks_like_service_line(p.name):
            score -= 12

    # Проверка согласованности суммы
    products_sum = sum((p.line_total if p.line_total is not None else p.price * p.quantity) for p in products)
    products_sum = safe_round2(products_sum)

    if meta.total is not None and products_sum is not None:
        diff = abs(meta.total - products_sum)
        if diff < 0.01:
            score += 18
        elif diff < 1.00:
            score += 10
        elif diff < 5.00:
            score += 4
        else:
            score -= min(diff / 3.0, 20)

    # Немного штрафуем за слишком малое число строк
    if len(lines) < 10:
        score -= 10

    # Штраф за плохие названия товаров
    bad_names = 0
    for p in products:
        name = p.name

        letters = len(re.findall(r"[A-Za-zА-Яа-яЁё]", name))
        weird = len(re.findall(r"[^A-Za-zА-Яа-яЁё0-9\s.,:%()/№\-]", name))

        if letters < 4 or weird > 3:
            bad_names += 1

        # штраф за слишком много одиночных символов
        if len(re.findall(r"\b[A-Za-zА-Яа-яЁё]\b", name)) >= 3:
            bad_names += 1

    score -= bad_names * 6

    score -= estimate_text_noise(raw_text)

    return score


def parse_candidate(candidate: OCRCandidate) -> Tuple[ReceiptMeta, List[Product]]:
    """
    Разбор одного OCR-кандидата.
    """
    fixed_text = apply_common_text_fixes(candidate.raw_text)
    lines = split_lines(fixed_text)

    meta = ReceiptMeta(
        store_name=extract_store_name(lines),
        store_address=extract_address(lines),
        receipt_date=extract_date(fixed_text),
        total=extract_total(fixed_text),
        subtotal=None,
    )

    products = build_products_from_lines(lines)
    return meta, products


def pick_best_candidate(candidates: List[OCRCandidate]) -> ReceiptResult:
    """
    Выбор лучшего OCR-варианта по общей оценке.
    """
    result = ReceiptResult(raw_ocr_variants=candidates)

    best_score = -1e9
    best_meta = ReceiptMeta()
    best_products: List[Product] = []
    best_text = ""

    for cand in candidates:
        meta, products = parse_candidate(cand)
        score = score_candidate(cand.lines, cand.raw_text, meta, products)

        if score > best_score:
            best_score = score
            best_meta = meta
            best_products = products
            best_text = cand.raw_text

    result.meta = best_meta
    result.products = best_products
    result.best_raw_text = best_text
    result.score = best_score
    
    
    if best_score >= 95:
        result.quality_label = "высокое"
    elif best_score >= 65:
        result.quality_label = "среднее"
    else:
        result.quality_label = "низкое"

    return result


# ============================================================
# OCR по координатам: дополнительная помощь для строк товара
# ============================================================

def build_lines_from_ocr_data(ocr_data: dict) -> List[str]:
    """
    Сбор строк из OCR-данных с координатами.
    Используется как дополнительный источник, если обычный OCR дал слабый результат.
    """
    n = len(ocr_data.get("text", []))
    rows = {}

    for i in range(n):
        text = str(ocr_data["text"][i]).strip()
        if not text:
            continue

        try:
            conf = float(ocr_data["conf"][i])
        except Exception:
            conf = -1

        if conf < 0:
            continue

        key = (
            ocr_data["block_num"][i],
            ocr_data["par_num"][i],
            ocr_data["line_num"][i]
        )

        rows.setdefault(key, []).append((
            int(ocr_data["left"][i]),
            text
        ))

    lines = []
    for _, items in sorted(rows.items()):
        items_sorted = sorted(items, key=lambda x: x[0])
        line = " ".join(t for _, t in items_sorted)
        line = clean_line(line)
        if line:
            lines.append(line)

    return lines


def fallback_candidate_from_data(variant_label: str, image_arr: np.ndarray, lang: str) -> Optional[OCRCandidate]:
    """
    Резервная стратегия: OCR с координатами, затем ручная сборка строк.
    """
    try:
        data = run_ocr_data(image_arr, lang=lang, psm=6)
        lines = build_lines_from_ocr_data(data)
        raw_text = "\n".join(lines)
        return OCRCandidate(
            label=f"{variant_label}_data_lines",
            raw_text=raw_text,
            lines=lines
        )
    except Exception:
        return None


# ============================================================
# CSV и вывод
# ============================================================

def save_products_csv(products: List[Product], csv_path: str) -> None:
    """Сохранение товаров в CSV."""
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["name", "quantity", "price", "line_total", "confidence"])
        for p in products:
            writer.writerow([
                p.name,
                f"{p.quantity:.3f}".rstrip("0").rstrip("."),
                f"{p.price:.2f}",
                "" if p.line_total is None else f"{p.line_total:.2f}",
                f"{p.confidence:.2f}",
            ])


def print_result(result: ReceiptResult, show_raw: bool = True) -> None:
    """Печать результата в консоль."""
    if show_raw:
        print("=== RAW OCR TEXT (BEST CANDIDATE) ===")
        print(result.best_raw_text)
        print()

    print("=== PARSED RECEIPT DATA ===")
    print(f"Store name   : {result.meta.store_name or 'NOT FOUND'}")
    print(f"Store address: {result.meta.store_address or 'NOT FOUND'}")
    print(f"Receipt date : {result.meta.receipt_date or 'NOT FOUND'}")
    print(f"Total        : {result.meta.total if result.meta.total is not None else 'NOT FOUND'}")
    print(f"Quality      : {result.quality_label} (score={result.score:.2f})")
    print()

    print("Products:")
    if not result.products:
        print("  No products found.")
        return

    for idx, p in enumerate(result.products, start=1):
        total_str = "" if p.line_total is None else f" | line_total={p.line_total:.2f}"
        print(
            f"  {idx:02d}. {p.name} | qty={p.quantity:g} | price={p.price:.2f}{total_str} | conf={p.confidence:.2f}"
        )


# ============================================================
# Основной пайплайн
# ============================================================

def prepare_receipt_image(image_path: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Подготовка изображения:
    - загрузка
    - поиск чека
    - выравнивание
    - авто-поворот
    Возвращает:
    - исходное изображение
    - выровненное изображение чека
    """
    original = load_image_bgr(image_path)

    quad = detect_receipt_contour(original)
    if quad is not None:
        prepared = perspective_warp(original, quad)
    else:
        prepared = original.copy()

    prepared = auto_rotate_if_needed(prepared)
    return original, prepared


def run_pipeline(image_path: str, lang: str = "rus+eng") -> ReceiptResult:
    """
    Полный запуск распознавания.
    """
    _, prepared = prepare_receipt_image(image_path)

    variants = build_preprocessed_variants(prepared)
    candidates = collect_ocr_candidates(variants, lang=lang)

    # Добавим резервные варианты из image_to_data
    for label, arr in variants[:3]:
        fallback = fallback_candidate_from_data(label, arr, lang=lang)
        if fallback is not None:
            candidates.append(fallback)

    if not candidates:
        return ReceiptResult()

    result = pick_best_candidate(candidates)
    return result


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    """Аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Улучшенное OCR-распознавание кассового чека"
    )
    parser.add_argument(
        "--image",
        required=True,
        help='Путь к изображению чека, например: "receipt.jpg"',
    )
    parser.add_argument(
        "--csv",
        default="products.csv",
        help='Путь к выходному CSV, например: "products.csv"',
    )
    parser.add_argument(
        "--lang",
        default="rus+eng",
        help='Языки Tesseract, например: "rus", "eng" или "rus+eng"',
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Не печатать сырой OCR-текст",
    )
    return parser.parse_args()


def main() -> None:
    """Точка входа."""
    args = parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        raise FileNotFoundError(f"Файл не найден: {image_path}")

    result = run_pipeline(str(image_path), lang=args.lang)

    print_result(result, show_raw=not args.no_raw)
    save_products_csv(result.products, args.csv)
    print(f"\nCSV saved to: {args.csv}")


if __name__ == "__main__":
    main()
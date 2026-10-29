# Ported from MediaWiki 1.39 (https://www.mediawiki.org/), (C) MediaWiki contributors: the parts that size and
# address images, from includes/filerepo/file/File.php and LocalFile.php (getUrl(), getWidth(), getHeight(),
# transform(), getUnscaledThumb(), thumbName(), getThumbUrl(), iconThumb(), canRender(), mustRender(), ...),
# includes/filerepo/FileRepo.php (getHashPath(), zone URLs, nameForThumb()), includes/media/MediaHandler.php,
# ImageHandler.php, TransformationalImageHandler.php, BitmapHandler.php, SvgHandler.php and DjVuHandler.php
# (parameter maps, validation, normaliseParams(), makeParamString(), getThumbType()), includes/media/
# MediaTransformOutput.php, ThumbnailImage.php, MediaTransformError.php and TransformParameterError.php (toHtml()),
# includes/media/MediaHandlerFactory.php, includes/BadFileLookup.php, Xml::element()/Xml::tags() and
# Html::srcSet(); the mock media handlers and uploads of the parser tests (tests/phpunit/mocks/media/,
# tests/parser/ParserTestRunner.php setupUploads()).
# Changed by a3ref contributors on 2026-10-30: translated to Python; no file storage, metadata extraction or
# thumbnail rendering: a file is its size, MIME type and URL, a thumbnail is the URL MediaWiki would give it (as the
# parser tests' mock handlers do); files come from a FileRepo the caller fills.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Files (images and other media), their thumbnails and the HTML of an image."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Union

from .site import NS_FILE
from .title import MalformedTitleException, Title, wf_array_to_cgi

# MEDIATYPE_* (includes/Defines.php)
MEDIATYPE_UNKNOWN = "UNKNOWN"
MEDIATYPE_BITMAP = "BITMAP"
MEDIATYPE_DRAWING = "DRAWING"
MEDIATYPE_AUDIO = "AUDIO"
MEDIATYPE_VIDEO = "VIDEO"
MEDIATYPE_MULTIMEDIA = "MULTIMEDIA"
MEDIATYPE_OFFICE = "OFFICE"
MEDIATYPE_TEXT = "TEXT"
MEDIATYPE_EXECUTABLE = "EXECUTABLE"
MEDIATYPE_ARCHIVE = "ARCHIVE"

# MainConfigSchema defaults
SVG_MAX_SIZE = 5120  # $wgSVGMaxSize
DJVU_OUTPUT_EXTENSION = "jpg"  # $wgDjvuOutputExtension

# English messages (languages/i18n/en.json)
_MESSAGES = {
    "thumbnail_error": "Error creating thumbnail: $1",
    "thumbnail_invalid_params": "Invalid thumbnail parameters",
    "djvu_page_error": "DjVu page out of range",
}


# ---- PHP helpers ----------------------------------------------------------------------------------------------

def php_round(value: float, precision: int = 0) -> float:
    """PHP round(): halves away from zero (Python's round() rounds halves to even)."""
    if precision >= 0:
        tmp = value * (10 ** precision)
    else:
        tmp = value / (10 ** -precision)
    # PHP pre-rounds the scaled value to 15 significant digits, so 1.005 * 100 rounds as 100.5
    tmp = float(f"{tmp:.15g}")
    r = math.copysign(math.floor(abs(tmp) + 0.5), tmp)
    if precision > 0:
        return r / (10 ** precision)
    if precision < 0:
        return r * (10 ** -precision)
    return r


def php_number(value) -> str:
    """PHP's string conversion of an int or float (precision 14): 150, 52.5, 1061.3333333333."""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, int):
        return str(value)
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = f"{value:.14G}"
    if "E" in text:
        mantissa, exp = text.split("E")
        if "." in mantissa:
            mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{mantissa}E{'+' if int(exp) > 0 else '-'}{abs(int(exp))}"
    return text


_NUMERIC = re.compile(r"^[ \t\n\r\v\f]*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[ \t\n\r\v\f]*$")


def php_is_numeric(value) -> bool:
    """PHP 8 is_numeric() of a string"""
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    return bool(_NUMERIC.match(value))


def php_intval(value) -> int:
    """PHP intval() of a string: the leading integer, 0 if there is none."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    m = re.match(r"^[ \t\n\r\v\f]*([+-]?[0-9]+)", value or "")
    return int(m.group(1)) if m else 0


def php_float(value) -> float:
    """PHP float conversion of a numeric string (0.0 for non-numeric)"""
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"^[ \t\n\r\v\f]*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)", value or "")
    return float(m.group(1)) if m else 0.0


def php_loose_equals_zero(value) -> bool:
    """PHP 8 `$value == 0`"""
    if value is False or value is None:
        return True
    if isinstance(value, (int, float)):
        return value == 0
    if php_is_numeric(value):
        return php_float(value) == 0
    return False


def rawurlencode(s: str) -> str:
    """PHP rawurlencode(): everything but [A-Za-z0-9_.~-] percent-encoded"""
    out = []
    for b in s.encode("utf-8", "surrogatepass"):
        c = chr(b)
        if c.isascii() and (c.isalnum() or c in "_.-~"):
            out.append(c)
        else:
            out.append(f"%{b:02X}")
    return "".join(out)


def encode_attribute(text) -> str:
    """Sanitizer::encodeAttribute()"""
    text = "" if text is None or text is False else ("1" if text is True else str(text))
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#039;"))
    return text.replace("\n", "&#10;").replace("\r", "&#13;").replace("\t", "&#9;")


def xml_expand_attributes(attribs: Optional[Mapping]) -> str:
    """Xml::expandAttributes()"""
    if attribs is None:
        return ""
    return "".join(f' {name}="{encode_attribute(value)}"' for name, value in attribs.items())


def xml_element(element: str, attribs: Optional[Mapping] = None, contents: Optional[str] = "") -> str:
    """Xml::element(): an XML element (with " />" when empty), contents escaped"""
    out = "<" + element + xml_expand_attributes(attribs)
    if contents is None:
        return out + ">"
    if contents == "":
        return out + " />"
    return out + ">" + contents.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + f"</{element}>"


def xml_tags(element: str, attribs: Optional[Mapping], contents: str) -> str:
    """Xml::tags(): an element with raw HTML contents"""
    return "<" + element + xml_expand_attributes(attribs) + ">" + contents + f"</{element}>"


def html_src_set(urls: Mapping[str, str]) -> str:
    """Html::srcSet(): a srcset attribute value from density -> URL"""
    candidates: dict[str, str] = {}
    for density, url in urls.items():
        # Cast density to float to strip 'x', then back to string to serve as array index.
        candidates[php_number(php_float(density))] = url
    # Remove duplicates that are the same as a smaller value
    unique: dict[str, str] = {}
    for density in sorted(candidates, key=float):
        if candidates[density] not in unique.values():
            unique[density] = candidates[density]
    # Append density info to the url
    return ", ".join(f"{url} {density}x" for density, url in unique.items())


def _msg(key: str, *params) -> str:
    text = _MESSAGES[key]
    for i, p in enumerate(params, 1):
        text = text.replace(f"${i}", str(p))
    return text


# ---- transform outputs ----------------------------------------------------------------------------------------

class MediaTransformOutput:
    """Base class for the output of MediaHandler::doTransform() and File::transform()."""

    def __init__(self):
        self.file: Optional[File] = None
        self.width = 0
        self.height = 0
        self.url: Union[str, bool, None] = False
        self.page = False
        self.path = False
        self.lang = False
        self.responsive_urls: dict[str, str] = {}

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_url(self):
        return self.url

    def is_error(self) -> bool:
        return False

    def to_html(self, options: Optional[dict] = None, *, legacy_media_dom: bool = True) -> str:
        raise NotImplementedError

    def link_wrap(self, link_attribs, contents: str, legacy_media_dom: bool = True) -> str:
        """Wrap some XHTML text in an anchor tag with the given attributes or, fallback to a span in the absence
        thereof."""
        if link_attribs and "href" in link_attribs:
            return xml_tags("a", link_attribs, contents)
        if legacy_media_dom:
            return contents
        return xml_tags("span", link_attribs or None, contents)

    def get_desc_link_attribs(self, title: Optional[str] = None, params: Union[str, dict, bool] = "",
                              legacy_media_dom: bool = True) -> dict:
        query: Union[dict, str] = dict(params) if isinstance(params, dict) else {}
        if self.page and self.page != 1:
            query["page"] = self.page
        if self.lang:
            query["lang"] = self.lang
        if isinstance(params, str) and params != "":
            query = params + "&" + wf_array_to_cgi(query)
        attribs = {"href": self.file.get_title().get_local_url(query)}
        attribs["class"] = "image" if legacy_media_dom else "mw-file-description"
        if title:
            attribs["title"] = title
        return attribs


class ThumbnailImage(MediaTransformOutput):
    """Media transform output for images"""

    def __init__(self, file: "File", url: str, path=False, parameters: Optional[dict] = None):
        super().__init__()
        params = {"page": False, "lang": False, **(parameters or {})}
        self.file = file
        self.url = url
        self.path = path
        # These should be integers when they get here. If not, there's a bug somewhere. But let's at least produce
        # valid HTML code regardless.
        self.width = int(php_round(php_float(params.get("width") or 0)))
        self.height = int(php_round(php_float(params.get("height") or 0)))
        self.page = params["page"]
        self.lang = params["lang"]

    def to_html(self, options: Optional[dict] = None, *, legacy_media_dom: bool = True,
                native_image_lazy_loading: bool = False) -> str:
        """Return HTML <img ... /> tag for the thumbnail, will include width and height attributes and a blank alt
        text (as required). ``options``: alt, title, valign, img-class, desc-link, desc-query, custom-url-link,
        custom-target-link, parser-extlink-*, custom-title-link, custom-title-link-query, file-link, no-dimensions,
        override-height, override-width, loading."""
        options = options or {}
        alt = options.get("alt") or ""
        query = options.get("desc-query") or ""

        attribs = {"alt": alt, "src": self.url, "decoding": "async"}
        if options.get("loading", native_image_lazy_loading):
            attribs["loading"] = options.get("loading") or "lazy"

        if options.get("custom-url-link"):
            link_attribs = {"href": options["custom-url-link"]}
            if options.get("title"):
                link_attribs["title"] = options["title"]
            if options.get("custom-target-link"):
                link_attribs["target"] = options["custom-target-link"]
            elif options.get("parser-extlink-target"):
                link_attribs["target"] = options["parser-extlink-target"]
            if options.get("parser-extlink-rel"):
                link_attribs["rel"] = options["parser-extlink-rel"]
        elif options.get("custom-title-link"):
            title = options["custom-title-link"]
            link_attribs = {
                "href": title.get_link_url(options.get("custom-title-link-query") or ""),
                "title": title.prefixed_text if not options.get("title") else options["title"],
            }
        elif options.get("desc-link"):
            link_attribs = self.get_desc_link_attribs(options.get("title") or None, query,
                                                      legacy_media_dom=legacy_media_dom)
        elif options.get("file-link"):
            link_attribs = {"href": self.file.get_url()}
        else:
            link_attribs = False
            if options.get("title"):
                if legacy_media_dom:
                    attribs["title"] = options["title"]
                else:
                    link_attribs = {"title": options["title"]}

        if not options.get("no-dimensions"):
            attribs["width"] = self.width
            attribs["height"] = self.height
        if options.get("valign"):
            attribs["style"] = f"vertical-align: {options['valign']}"
        if options.get("img-class"):
            attribs["class"] = options["img-class"]
        if "override-height" in options:
            attribs["height"] = php_number(options["override-height"])
        if "override-width" in options:
            attribs["width"] = php_number(options["override-width"])

        # Additional densities for responsive images, if specified. If any of these urls is the same as src url,
        # it'll be excluded.
        responsive_urls = {k: v for k, v in self.responsive_urls.items() if v != self.url}
        if responsive_urls:
            attribs["srcset"] = html_src_set(responsive_urls)

        return self.link_wrap(link_attribs, xml_element("img", attribs), legacy_media_dom)


class MediaTransformError(MediaTransformOutput):
    """Basic media transform error class"""

    def __init__(self, msg: str, width, height, *args):
        super().__init__()
        self.msg_key = msg
        self.msg_params = args
        self.width = php_intval(width)
        self.height = php_intval(height)
        self.url = False
        self.path = False

    def to_html(self, options: Optional[dict] = None, **_kw) -> str:
        return (f'<div class="MediaTransformError" style="width: {self.width}px; height: {self.height}px; '
                f'display:inline-block;">{self.get_html_msg()}</div>')

    def to_text(self) -> str:
        return _msg(self.msg_key, *self.msg_params)

    def get_html_msg(self) -> str:
        from .html import htmlspecialchars

        return htmlspecialchars(self.to_text())

    def is_error(self) -> bool:
        return True


class TransformParameterError(MediaTransformError):
    """Shortcut class for parameter validation errors"""

    def __init__(self, params: dict):
        super().__init__("thumbnail_error", max(php_intval(params.get("width", 0)), 120),
                         max(php_intval(params.get("height", 0)), 120), _msg("thumbnail_invalid_params"))


# ---- media handlers -------------------------------------------------------------------------------------------

def fit_box_width(box_width: float, box_height: float, max_height: float) -> int:
    """MediaHandler::fitBoxWidth(): calculate the largest thumbnail width for a given original file size such
    that the thumbnail's height is at most max_height."""
    ideal_width = box_width * max_height / box_height
    rounded_up = math.ceil(ideal_width)
    if php_round(rounded_up * box_height / box_width) > max_height:
        return int(math.floor(ideal_width))
    return rounded_up


def scale_height(src_width: float, src_height: float, dst_width: float) -> int:
    """File::scaleHeight(): calculate the height of a thumbnail using the source and destination width"""
    # Exact integer multiply followed by division
    if src_width == 0:
        return 0
    return int(php_round(src_height * dst_width / src_width))


# MimeAnalyzer: extensions of the MIME types the handlers know
_MIME_EXTENSIONS = {
    "image/jpeg": ("jpg", "jpeg", "jpe"),
    "image/png": ("png",),
    "image/gif": ("gif",),
    "image/tiff": ("tiff", "tif"),
    "image/webp": ("webp",),
    "image/x-ms-bmp": ("bmp",),
    "image/x-bmp": ("bmp",),
    "image/x-xcf": ("xcf",),
    "image/svg+xml": ("svg",),
    "image/vnd.djvu": ("djvu", "djv"),
}


class MediaHandler:
    """Base media handler class"""
    TRANSFORM_LATER = 1

    def is_enabled(self) -> bool:
        return True

    def get_param_map(self) -> dict[str, str]:
        return {}

    def validate_param(self, name: str, value) -> bool:
        return False

    def make_param_string(self, params: dict) -> Union[str, bool]:
        return False

    def normalise_params(self, image: "File", params: dict) -> bool:
        return True

    def can_render(self, file: "File") -> bool:
        return True

    def must_render(self, file: "File") -> bool:
        return False

    def is_vectorized(self, file: "File") -> bool:
        return False

    def is_multipage(self, file: "File") -> bool:
        return False

    def page_count(self, file: "File"):
        return False

    def get_page_dimensions(self, image: "File", page: int):
        return False

    def get_thumb_type(self, ext: str, mime: str, params=None) -> tuple[str, str]:
        known = _MIME_EXTENSIONS.get(mime)
        if (not ext or (known is not None and ext not in known)) and known:
            # The extension is not valid for this MIME type and we do recognize the MIME type
            return known[0], mime
        # The extension is correct (true) or the MIME type is unknown to MediaWiki (null)
        return ext, mime

    def get_matched_language(self, user_preferred_language: str, svg_languages: Iterable[str]):
        return None

    def get_available_languages(self, file: "File") -> list[str]:
        return []

    def parser_transform_hook(self, parser, file: "File") -> None:
        pass

    def do_transform(self, image: "File", dst_path, dst_url: str, params: dict, flags: int = 0):
        raise NotImplementedError

    def get_transform(self, image: "File", dst_path, dst_url: str, params: dict):
        return self.do_transform(image, dst_path, dst_url, params, self.TRANSFORM_LATER)


class ImageHandler(MediaHandler):
    """Media handler abstract base class for images"""

    def can_render(self, file: "File") -> bool:
        return bool(file.get_width() and file.get_height())

    def get_param_map(self) -> dict[str, str]:
        return {"img_width": "width"}

    def validate_param(self, name: str, value) -> bool:
        return name in ("width", "height") and php_float(value) > 0

    def make_param_string(self, params: dict) -> Union[str, bool]:
        if "physicalWidth" in params:
            width = params["physicalWidth"]
        elif "width" in params:
            width = params["width"]
        else:
            raise ValueError("No width specified to makeParamString")
        return f"{php_number(width)}px"

    def normalise_params(self, image: "File", params: dict) -> bool:
        if "width" not in params:
            return False
        if "page" not in params:
            params["page"] = 1
        else:
            params["page"] = php_intval(params["page"])
            page_count = image.page_count()
            if page_count is False:
                # PHP: $page > false is true for any page but 0, and then false < 1
                params["page"] = 1
            else:
                if params["page"] > page_count:
                    params["page"] = page_count
                if params["page"] < 1:
                    params["page"] = 1

        src_width = image.get_width(params["page"])
        src_height = image.get_height(params["page"])

        if "height" in params and params["height"] != -1:
            # Height & width were both set
            if params["width"] * src_height > params["height"] * src_width:
                # Height is the relative smaller dimension, so scale width accordingly
                params["width"] = fit_box_width(src_width, src_height, params["height"])
                if params["width"] == 0:
                    # Very small image, so we need to rely on client side scaling :(
                    params["width"] = 1
                params["physicalWidth"] = params["width"]
            else:
                # Height was crap, unset it so that it will be calculated later
                del params["height"]

        if "physicalWidth" not in params:
            # Passed all validations, so set the physicalWidth
            params["physicalWidth"] = params["width"]

        # Because thumbs are only referred to by width, the height always needs to be scaled by the width to keep
        # the thumbnail sizes consistent, even if it was set inside the if block above
        params["physicalHeight"] = scale_height(src_width, src_height, params["physicalWidth"])

        # Set the height if it was not validated in the if block higher up
        if "height" not in params or params["height"] == -1:
            params["height"] = params["physicalHeight"]

        return self._validate_thumb_params(params, src_width, src_height)

    @staticmethod
    def _validate_thumb_params(params: dict, src_width, src_height) -> bool:
        """ImageHandler::validateThumbParams(), which changes physicalWidth and physicalHeight by reference"""
        width = php_intval(params["physicalWidth"])
        params["physicalWidth"] = width
        if width <= 0:
            return False
        if src_width <= 0:
            return False
        height = scale_height(src_width, src_height, width)
        if height == 0:
            # Force height to be at least 1 pixel
            height = 1
        params["physicalHeight"] = height
        return True


class TransformationalImageHandler(ImageHandler):
    """Handler for images that need to be transformed"""

    def normalise_params(self, image: "File", params: dict) -> bool:
        if not super().normalise_params(image, params):
            return False
        # Obtain the source, pre-rotation dimensions
        src_width = image.get_width(params["page"])
        src_height = image.get_height(params["page"])
        # Don't make an image bigger than the source
        if params["physicalWidth"] >= src_width:
            params["physicalWidth"] = src_width
            params["physicalHeight"] = src_height
        return True

    def do_transform(self, image: "File", dst_path, dst_url: str, params: dict, flags: int = 0):
        """Create a thumbnail: here, as the parser tests' MockImageHandler::doFakeTransform() does, the
        ThumbnailImage the scaler would produce, without scaling anything."""
        params = dict(params)
        if not self.normalise_params(image, params):
            return TransformParameterError(params)
        scaler_params = {
            # The size to which the image will be resized
            "physicalWidth": params["physicalWidth"],
            "physicalHeight": params["physicalHeight"],
            # The size of the image on the page
            "clientWidth": params["width"],
            "clientHeight": params["height"],
            # Properties of the original image
            "srcWidth": image.get_width(),
            "srcHeight": image.get_height(),
        }
        # In some cases, we do not bother generating a thumbnail.
        if (not image.must_render() and scaler_params["physicalWidth"] == scaler_params["srcWidth"]
                and scaler_params["physicalHeight"] == scaler_params["srcHeight"]):
            # normaliseParams (or the user) wants us to return the unscaled image
            return self.get_client_scaling_thumbnail_image(image, scaler_params)
        return ThumbnailImage(image, dst_url, False, params)

    @staticmethod
    def get_client_scaling_thumbnail_image(image: "File", scaler_params: dict) -> ThumbnailImage:
        params = {"width": scaler_params["clientWidth"], "height": scaler_params["clientHeight"]}
        return ThumbnailImage(image, image.get_url(), None, params)


class BitmapHandler(TransformationalImageHandler):
    """Generic handler for bitmap images (JpegHandler, PNGHandler, GIFHandler, ... size them the same way)"""

    def make_param_string(self, params: dict) -> Union[str, bool]:
        res = super().make_param_string(params)
        if params.get("interlace"):
            return f"interlaced-{res}"
        return res

    def validate_param(self, name: str, value) -> bool:
        if name == "interlace":
            return value is False or value is True
        return super().validate_param(name, value)

    def normalise_params(self, image: "File", params: dict) -> bool:
        if not super().normalise_params(image, params):
            return False
        # $wgMaxInterlacingAreas is empty by default
        params["interlace"] = False
        return True


_LANGUAGE_TAG = re.compile(r"^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$")


class SvgHandler(ImageHandler):
    """Handler for SVG images."""
    SVG_DEFAULT_RENDER_LANG = "en"

    def must_render(self, file: "File") -> bool:
        return True

    def is_vectorized(self, file: "File") -> bool:
        return True

    def get_param_map(self) -> dict[str, str]:
        return {"img_lang": "lang", "img_width": "width"}

    def validate_param(self, name: str, value) -> bool:
        if name in ("width", "height"):
            # Reject negative heights, widths
            return php_float(value) > 0
        if name == "lang":
            # Validate code (LanguageCode::isWellFormedLanguageTag(), simplified to the BCP 47 shape)
            return value != "" and bool(_LANGUAGE_TAG.match(value))
        # Only lang, width and height are acceptable keys
        return False

    def make_param_string(self, params: dict) -> Union[str, bool]:
        lang = ""
        code = self._get_language_from_params(params)
        if code != self.SVG_DEFAULT_RENDER_LANG:
            lang = "lang" + code.lower() + "-"
        if "width" not in params:
            return False
        return f"{lang}{php_number(params['width'])}px"

    def _get_language_from_params(self, params: dict) -> str:
        return params.get("lang") or params.get("targetlang") or self.SVG_DEFAULT_RENDER_LANG

    def normalise_params(self, image: "File", params: dict) -> bool:
        if super().normalise_params(image, params):
            self._normalise_params_internal(image, params)
            return True
        return False

    def _normalise_params_internal(self, image: "File", params: dict) -> None:
        # Don't make an image bigger than wgMaxSVGSize on the smaller side
        if params["physicalWidth"] <= params["physicalHeight"]:
            if params["physicalWidth"] > SVG_MAX_SIZE:
                src_width = image.get_width(params["page"])
                src_height = image.get_height(params["page"])
                params["physicalWidth"] = SVG_MAX_SIZE
                params["physicalHeight"] = scale_height(src_width, src_height, SVG_MAX_SIZE)
        elif params["physicalHeight"] > SVG_MAX_SIZE:
            src_width = image.get_width(params["page"])
            src_height = image.get_height(params["page"])
            params["physicalWidth"] = scale_height(src_height, src_width, SVG_MAX_SIZE)
            params["physicalHeight"] = SVG_MAX_SIZE
        # To prevent the proliferation of thumbnails in languages not present in SVGs, unless explicitly forced by
        # user.
        if "targetlang" in params and not image.get_matched_language(params["targetlang"]):
            del params["targetlang"]

    def get_thumb_type(self, ext: str, mime: str, params=None) -> tuple[str, str]:
        return "png", "image/png"

    def get_available_languages(self, file: "File") -> list[str]:
        return list(dict.fromkeys(lang.lower() for lang in file.languages))

    def get_matched_language(self, user_preferred_language: str, svg_languages: Iterable[str]):
        # Explicitly requested undetermined language (text without svg systemLanguage attribute)
        if user_preferred_language == "und":
            return "und"
        for svg_lang in svg_languages:
            if svg_lang.lower() == user_preferred_language.lower():
                return svg_lang
            trimmed = svg_lang
            while "-" in trimmed:
                trimmed = trimmed[:trimmed.rfind("-")]
                if trimmed.lower() == user_preferred_language.lower():
                    return svg_lang
        return None

    def do_transform(self, image: "File", dst_path, dst_url: str, params: dict, flags: int = 0):
        """As the parser tests' MockSvgHandler (no rasterizing): the thumbnail's URL and size."""
        params = dict(params)
        if not self.normalise_params(image, params):
            return TransformParameterError(params)
        return ThumbnailImage(image, dst_url, False, params)


class DjVuHandler(ImageHandler):
    """Handler for DjVu images"""

    def __init__(self, enabled: bool = False):
        # isEnabled(): $wgDjvuRenderer, $wgDjvuDump and $wgDjvuToXML are unset by default
        self.enabled = enabled

    def is_enabled(self) -> bool:
        return self.enabled

    def must_render(self, file: "File") -> bool:
        return True

    def is_multipage(self, file: "File") -> bool:
        return True

    def get_param_map(self) -> dict[str, str]:
        return {"img_width": "width", "img_page": "page"}

    def validate_param(self, name: str, value) -> bool:
        if name == "page" and str(value).strip() != str(php_intval(value)):
            # Extra junk on the end of page, probably actually a caption
            # e.g. [[File:Foo.djvu|thumb|Page 3 of the document shows foo]]
            return False
        return name in ("width", "height", "page") and php_float(value) > 0

    def make_param_string(self, params: dict) -> Union[str, bool]:
        page = params.get("page", 1)
        if "width" not in params:
            return False
        return f"page{page}-{php_number(params['width'])}px"

    def get_thumb_type(self, ext: str, mime: str, params=None) -> tuple[str, str]:
        return DJVU_OUTPUT_EXTENSION, "image/jpeg"

    def page_count(self, file: "File"):
        return len(file.pages) if file.pages else False

    def get_page_dimensions(self, image: "File", page: int):
        index = page - 1  # MW starts pages at 1
        if image.pages and 0 <= index < len(image.pages):
            width, height = image.pages[index]
            return {"width": width, "height": height}
        return False

    def do_transform(self, image: "File", dst_path, dst_url: str, params: dict, flags: int = 0):
        """As the parser tests' MockDjVuHandler (no rendering)."""
        params = dict(params)
        if not self.normalise_params(image, params):
            return TransformParameterError(params)
        width, height, page = params["width"], params["height"], params["page"]
        if page > self.page_count(image):
            return MediaTransformError("thumbnail_error", width, height, _msg("djvu_page_error"))
        return ThumbnailImage(image, dst_url, dst_path, {"width": width, "height": height, "page": page})


def default_handlers(djvu: bool = False) -> dict[str, MediaHandler]:
    """MediaHandlerFactory: MIME type -> handler (the core handlers; the parser tests' mock handlers behave the
    same, and enable DjVu)."""
    bitmap = BitmapHandler()
    return {
        "image/jpeg": bitmap,
        "image/png": bitmap,
        "image/gif": bitmap,
        "image/tiff": bitmap,
        "image/webp": bitmap,
        "image/x-ms-bmp": bitmap,
        "image/x-bmp": bitmap,
        "image/x-xcf": bitmap,
        "image/svg+xml": SvgHandler(),
        "image/vnd.djvu": DjVuHandler(enabled=djvu),
    }


# ---- files ----------------------------------------------------------------------------------------------------

def _media_type(mime: str) -> str:
    if mime in ("image/svg+xml",):
        return MEDIATYPE_DRAWING
    if mime == "image/vnd.djvu":
        return MEDIATYPE_BITMAP
    major = mime.split("/")[0]
    return {"image": MEDIATYPE_BITMAP, "audio": MEDIATYPE_AUDIO, "video": MEDIATYPE_VIDEO,
            "text": MEDIATYPE_TEXT}.get(major, MEDIATYPE_UNKNOWN)


def normalize_extension(ext: str) -> str:
    """File::normalizeExtension()"""
    lower = ext.lower()
    squish = {"htm": "html", "jpeg": "jpg", "mpeg": "mpg", "tiff": "tif", "ogv": "ogg"}
    if lower in squish:
        return squish[lower]
    if re.match(r"^[0-9a-z]+$", lower):
        return lower
    return ""


@dataclass
class FileInfo:
    """What a repository knows about one file."""
    width: int
    height: int
    mime: str
    url: Optional[str] = None  # None: computed from the repository URL and the hash path
    size: int = 0
    media_type: Optional[str] = None
    pages: Optional[list[tuple[int, int]]] = None  # (width, height) of each page of a multi-page file (DjVu)
    languages: tuple[str, ...] = ()  # SVG: the languages it has full translations for
    sha1: str = ""


class File:
    """A file in a repository (LocalFile): a title, a size, a MIME type and a URL."""

    def __init__(self, title: Title, info: FileInfo, repo: "FileRepo"):
        self.title = title
        self.info = info
        self.repo = repo
        self.name = title.db_key
        self.pages = info.pages
        self.languages = info.languages
        self.redirected_from: Optional[str] = None
        dot = self.name.rfind(".")
        self.extension = self.name[dot + 1:] if dot != -1 else ""
        self._handler: Union[MediaHandler, bool, None] = None

    def __repr__(self) -> str:
        return f"File({self.name!r}, {self.info.width}x{self.info.height}, {self.info.mime!r})"

    # -- basic properties --

    def get_name(self) -> str:
        return self.name

    def get_title(self) -> Title:
        return self.title

    def get_extension(self) -> str:
        """The normalized file extension"""
        return normalize_extension(self.extension)

    def get_mime_type(self) -> str:
        return self.info.mime

    def get_media_type(self) -> str:
        return self.info.media_type or _media_type(self.info.mime)

    def get_size(self) -> int:
        return self.info.size

    def exists(self) -> bool:
        return True

    def get_last_error(self) -> str:
        return ""

    def get_handler(self) -> Optional[MediaHandler]:
        """The media handler for this file's MIME type, None if there is none (or it is disabled)"""
        if self._handler is None:
            handler = self.repo.handlers.get(self.info.mime)
            self._handler = handler if handler is not None and handler.is_enabled() else False
        return self._handler or None

    def is_multipage(self) -> bool:
        handler = self.get_handler()
        return bool(handler and handler.is_multipage(self))

    def page_count(self):
        handler = self.get_handler()
        return handler.page_count(self) if handler else False

    def get_width(self, page=1) -> int:
        """LocalFile::getWidth(): the width of the file (or of a page of a multi-page file)"""
        page = php_intval(page) if page is not False else 1
        if page < 1:
            page = 1
        if self.is_multipage():
            dim = self.get_handler().get_page_dimensions(self, page)
            return dim["width"] if dim else 0
        return self.info.width

    def get_height(self, page=1) -> int:
        page = php_intval(page) if page is not False else 1
        if page < 1:
            page = 1
        if self.is_multipage():
            dim = self.get_handler().get_page_dimensions(self, page)
            return dim["height"] if dim else 0
        return self.info.height

    def can_render(self) -> bool:
        handler = self.get_handler()
        return bool(handler and handler.can_render(self) and self.exists())

    def must_render(self) -> bool:
        handler = self.get_handler()
        return bool(handler and handler.must_render(self))

    def allow_inline_display(self) -> bool:
        return self.can_render()

    def is_vectorized(self) -> bool:
        handler = self.get_handler()
        return bool(handler and handler.is_vectorized(self))

    def get_matched_language(self, lang: str):
        handler = self.get_handler()
        if not handler:
            return None
        return handler.get_matched_language(lang, handler.get_available_languages(self))

    # -- URLs --

    def get_hash_path(self) -> str:
        return self.repo.get_hash_path(self.name)

    def get_url_rel(self) -> str:
        return self.get_hash_path() + rawurlencode(self.name)

    def get_url(self) -> str:
        """The URL of the file itself"""
        if self.info.url:
            return self.info.url
        return self.repo.get_zone_url("public") + "/" + self.get_url_rel()

    def get_thumb_url(self, suffix: Union[str, bool] = False) -> str:
        """The URL of the thumbnail directory, or a particular file if suffix is given"""
        path = self.repo.get_zone_url("thumb") + "/" + self.get_url_rel()
        if suffix is not False:
            path += "/" + rawurlencode(suffix)
        return path

    def thumb_name(self, params: dict) -> Optional[str]:
        """The name of a thumbnail file given its parameters"""
        return self.generate_thumb_name(self.repo.name_for_thumb(self.name), params)

    def generate_thumb_name(self, name: str, params: dict) -> Optional[str]:
        handler = self.get_handler()
        if not handler:
            return None
        extension = self.get_extension()
        thumb_ext, _ = handler.get_thumb_type(extension, self.get_mime_type(), params)
        thumb_name = str(handler.make_param_string(params))
        thumb_name += "-" + name
        if thumb_ext != extension:
            thumb_name += f".{thumb_ext}"
        return thumb_name

    # -- transforms --

    def transform(self, params: dict, flags: int = 0) -> Optional[MediaTransformOutput]:
        """Transform a media file: the ThumbnailImage (or error) for these parameters (width, height, page, ...)"""
        if not self.can_render():
            return self.icon_thumb()  # not a bitmap or renderable image, don't try
        handler = self.get_handler()
        normalised_params = dict(params)
        handler.normalise_params(self, normalised_params)
        thumb_name = self.thumb_name(normalised_params)
        thumb_url = self.get_thumb_url(thumb_name)
        return handler.do_transform(self, False, thumb_url, dict(params), flags)

    def get_unscaled_thumb(self, handler_params: Optional[dict] = None):
        """A MediaTransformOutput of the file at its own size"""
        hp = dict(handler_params or {})
        page = hp.get("page", False)
        width = self.get_width(page)
        if not width:
            return self.icon_thumb()
        hp["width"] = width
        # be sure to ignore any height specification as well (T64258)
        hp.pop("height", None)
        return self.transform(hp)

    def icon_thumb(self) -> Optional[ThumbnailImage]:
        """A generic icon for the file's type (resources/assets/file-type-icons/)"""
        assets_path = f"{self.repo.resource_base_path}/resources/assets/file-type-icons/"
        for icon in (f"fileicon-{self.get_extension()}.png", "fileicon.png"):
            if icon in FILE_TYPE_ICONS:
                return ThumbnailImage(self, assets_path + icon, False, {"width": 120, "height": 120})
        return None

    def get_dimensions_string(self) -> str:
        """ImageHandler::getDimensionsString() in English"""
        pages = self.page_count()
        if pages and pages > 1:
            return f"{self.get_width():,} × {self.get_height():,} × {pages:,} pages"
        return f"{self.get_width():,} × {self.get_height():,}"


# resources/assets/file-type-icons/ of MediaWiki 1.39
FILE_TYPE_ICONS = frozenset(f"fileicon-{ext}.png" for ext in (
    "c", "cpp", "deb", "djvu", "dvi", "exe", "h", "html", "iso", "java", "mid", "mov", "mpga", "o", "ogg", "pdf",
    "ps", "psd", "rm", "rpm", "svg", "tar", "tex", "ttf", "txt", "xcf")) | {"fileicon.png"}


class FileRepo:
    """The files of a wiki: a mapping of file names to their size, MIME type and URL (FileRepo/LocalRepo with
    RepoGroup::findFile()). ``files``: name -> (width, height, mime, url) or FileInfo; names with spaces or
    underscores, without the File: prefix; url may be None to compute it from ``url`` and the hash path."""

    def __init__(self, url: str = "", files: Optional[Mapping[str, Union[tuple, FileInfo]]] = None, *,
                 thumb_url: Optional[str] = None, hash_levels: int = 2,
                 handlers: Optional[Mapping[str, MediaHandler]] = None, resource_base_path: str = ""):
        self.url = url
        self.thumb_url = thumb_url if thumb_url is not None else f"{url}/thumb"
        self.hash_levels = hash_levels
        self.handlers = dict(handlers) if handlers is not None else default_handlers()
        self.resource_base_path = resource_base_path
        self.abbrv_threshold = 255
        self.infos: dict[str, FileInfo] = {}
        for name, info in (files or {}).items():
            if not isinstance(info, FileInfo):
                width, height, mime, *rest = info
                info = FileInfo(width, height, mime, rest[0] if rest else None)
            self.infos[name.replace(" ", "_")] = info
        self._cache: dict[tuple[int, str], File] = {}

    def __bool__(self) -> bool:
        return True

    def get(self, title: Title) -> Optional[File]:
        """RepoGroup::findFile() without redirects: the file a File: (or Media:) title names, or None"""
        if title is None or title.is_external():
            return None
        name = title.db_key
        info = self.infos.get(name)
        if info is None:
            return None
        key = (id(title.site), name)
        file = self._cache.get(key)
        if file is None:
            file = self._cache[key] = File(Title.make_title(NS_FILE, name, site=title.site), info, self)
        return file

    def get_zone_url(self, zone: str) -> str:
        return self.thumb_url if zone == "thumb" else self.url

    def get_hash_path(self, name: str) -> str:
        """FileRepo::getHashPathForLevel(): a/ab/ for the MD5 of the name"""
        if self.hash_levels == 0:
            return ""
        digest = hashlib.md5(name.encode("utf-8")).hexdigest()
        return "".join(digest[:i] + "/" for i in range(1, self.hash_levels + 1))

    def name_for_thumb(self, name: str) -> str:
        """FileRepo::nameForThumb(): a shorter name for thumbnails of files with very long names"""
        if len(name.encode("utf-8")) > self.abbrv_threshold:
            dot = name.rfind(".")
            ext = name[dot + 1:].lower() if dot != -1 else ""
            return "thumbnail" if ext == "" else f"thumbnail.{ext}"
        return name


EMPTY_FILES = FileRepo()


def test_files() -> FileRepo:
    """The uploads of MediaWiki's parser tests (ParserTestRunner::setupUploads(), the MockLocalRepo with URL
    http://example.com/images and the mock media handlers, which enable DjVu)."""
    return FileRepo("http://example.com/images", {
        "Foobar.jpg": FileInfo(1941, 220, "image/jpeg", size=7881, media_type=MEDIATYPE_BITMAP),
        "Thumb.png": FileInfo(135, 135, "image/png", size=22589, media_type=MEDIATYPE_BITMAP),
        "Foobar.svg": FileInfo(240, 180, "image/svg+xml", size=12345, media_type=MEDIATYPE_DRAWING,
                               languages=("en", "ru")),
        "Bad.jpg": FileInfo(320, 240, "image/jpeg", size=12345, media_type=MEDIATYPE_BITMAP),
        "Video.ogv": FileInfo(320, 240, "application/ogg", size=12345, media_type=MEDIATYPE_VIDEO),
        "Audio.oga": FileInfo(0, 0, "application/ogg", size=12345, media_type=MEDIATYPE_AUDIO),
        "LoremIpsum.djvu": FileInfo(2480, 3508, "image/vnd.djvu", size=3249, media_type=MEDIATYPE_OFFICE,
                                    pages=[(2480, 3508)] * 5),
    }, handlers=default_handlers(djvu=True))


test_files.__test__ = False  # not a test for test runners that collect test_* functions


class BadFileLookup:
    """Which files must not be shown inline: the list in [[MediaWiki:Bad image list]] (BadFileLookup)."""

    def __init__(self, list_callback: Callable[[], str], find_file: Callable[[str], Optional[File]], site):
        self.list_callback = list_callback
        self.find_file = find_file
        self.site = site
        self.bad_files: Optional[dict[str, dict[int, dict[str, bool]]]] = None

    def is_bad_file(self, name: str, context_title: Optional[Title] = None) -> bool:
        """Determine if a file exists on the 'bad image list'."""
        # Handle redirects; callers almost always hit RepoGroup::findFile() anyway
        file = self.find_file(name)
        if file:
            name = file.get_title().db_key
        if self.bad_files is None:
            self.bad_files = self._build_bad_files_list(self.list_callback())
        return name in self.bad_files and (
            context_title is None
            or context_title.db_key not in self.bad_files[name].get(context_title.namespace, {}))

    def _build_bad_files_list(self, text: str) -> dict:
        ret: dict = {}
        for line in text.split("\n"):
            # List items only
            if not line.startswith("*"):
                continue
            # Find all links
            links = re.findall(r"\[\[:?(.*?)\]\]", line)
            if not links:
                continue
            file_db_key = None
            exceptions: dict[int, dict[str, bool]] = {}
            for i, title_text in enumerate(links):
                try:
                    title = Title.new_from_text_throw(title_text, site=self.site)
                except MalformedTitleException:
                    continue
                if i == 0:
                    file_db_key = title.db_key
                else:
                    exceptions.setdefault(title.namespace, {})[title.db_key] = True
            if file_db_key is not None:
                ret[file_db_key] = exceptions
        return ret


__all__ = ["File", "FileInfo", "FileRepo", "EMPTY_FILES", "test_files", "ThumbnailImage", "MediaTransformError",
           "TransformParameterError", "MediaTransformOutput", "MediaHandler", "ImageHandler", "BitmapHandler",
           "SvgHandler", "DjVuHandler", "BadFileLookup", "default_handlers"]

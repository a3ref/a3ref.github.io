# Ported from MediaWiki 1.39 includes/gallery/ImageGalleryBase.php, TraditionalImageGallery.php,
# NolinesImageGallery.php, PackedImageGallery.php, PackedHoverImageGallery.php, PackedOverlayImageGallery.php and
# SlideshowImageGallery.php, and Parser::renderImageGallery() of includes/parser/Parser.php
# (https://www.mediawiki.org/), (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the galleries always render through the parser
# (files, link renderer, bad image list); no hooks, no ResourceLoader modules (so the slideshow's client-side
# script is not added).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""<gallery>: image galleries."""
from __future__ import annotations

import math
import re
from typing import Optional
from urllib.parse import unquote

from .files import MEDIATYPE_AUDIO, php_number, xml_expand_attributes
from .html import htmlspecialchars, raw_element
from .linker import get_image_link_mto_params, legacy_media_dom, make_broken_image_link_obj, \
    process_responsive_images
from .site import NS_FILE
from .title import Title

# $wgGalleryOptions defaults (Setup.php)
GALLERY_OPTIONS = {
    "imagesPerRow": 0,
    "imageWidth": 120,
    "imageHeight": 120,
    "captionLength": True,
    "showBytes": True,
    "showDimensions": True,
    "mode": "traditional",
}

LOADING_DEFAULT = 1
LOADING_LAZY = 2


class ImageGalleryClassNotFoundException(Exception):
    pass


class ImageGalleryBase:
    """Image gallery. Add images to the gallery using add(), then render that list to HTML using to_html()."""

    def __init__(self, mode: str = "traditional", options: Optional[dict] = None):
        gallery_options = {**GALLERY_OPTIONS, **(options or {})}
        self.images: list[tuple] = []
        self.show_bytes = gallery_options["showBytes"]
        self.show_dimensions = gallery_options["showDimensions"]
        self.show_filename = True
        self.parser = None
        self.hide_bad_images = False
        self.per_row = gallery_options["imagesPerRow"]
        self.widths = gallery_options["imageWidth"]
        self.heights = gallery_options["imageHeight"]
        self.caption_length = gallery_options["captionLength"]
        self.mode = mode
        self.caption: str | bool = False
        self.attribs: dict = {}
        self.context_title: Optional[Title] = None

    @staticmethod
    def factory(mode: str | bool = False, options: Optional[dict] = None) -> "ImageGalleryBase":
        """Get a new image gallery for the mode ('traditional' by default)."""
        if not mode:
            mode = {**GALLERY_OPTIONS, **(options or {})}["mode"]
        mode = mode.lower()
        if mode in MODE_MAPPING:
            return MODE_MAPPING[mode](mode, options)
        raise ImageGalleryClassNotFoundException(f"No gallery class registered for mode {mode}")

    def set_parser(self, parser) -> None:
        self.parser = parser

    def set_hide_bad_images(self, flag: bool = True) -> None:
        self.hide_bad_images = flag

    def set_caption(self, caption: str) -> None:
        """Set the caption (as plain text)"""
        self.caption = htmlspecialchars(caption)

    def set_caption_html(self, caption: str) -> None:
        """Set the caption (as HTML)"""
        self.caption = caption

    def set_per_row(self, num) -> None:
        """Set how many images will be displayed per row."""
        from .files import php_float, php_intval

        if php_float(num) >= 0:
            self.per_row = php_intval(num)

    def set_widths(self, num) -> None:
        """Set how wide each image will be, in pixels."""
        from .parser_links import LinksMixin

        parsed = LinksMixin.parse_width_param(num, False)
        if parsed.get("width", 0) > 0:
            self.widths = parsed["width"]

    def set_heights(self, num) -> None:
        """Set how high each image will be, in pixels."""
        from .parser_links import LinksMixin

        parsed = LinksMixin.parse_width_param(num, False)
        if parsed.get("width", 0) > 0:
            self.heights = parsed["width"]

    def set_additional_options(self, options: dict) -> None:
        """Allow setting additional options. This is meant to allow extensions to add additional parameters to
        <gallery> parser tag."""

    def add(self, title: Title, html: str = "", alt: str = "", link: str = "", handler_opts: Optional[dict] = None,
            loading: int = LOADING_DEFAULT, image_options: Optional[dict] = None) -> None:
        """Add an image to the gallery."""
        self.images.append((title, html, alt, link, handler_opts or {}, loading, image_options))

    def is_empty(self) -> bool:
        return not self.images

    def set_show_dimensions(self, f: bool) -> None:
        self.show_dimensions = bool(f)

    def set_show_bytes(self, f: bool) -> None:
        self.show_bytes = bool(f)

    def set_show_filename(self, f: bool) -> None:
        self.show_filename = bool(f)

    def set_attributes(self, attribs: dict) -> None:
        """Set arbitrary attributes to go on the HTML gallery output element."""
        self.attribs = dict(attribs)

    def count(self) -> int:
        return len(self.images)

    def set_context_title(self, title: Title) -> None:
        self.context_title = title

    def to_html(self) -> str:
        raise NotImplementedError


class TraditionalImageGallery(ImageGalleryBase):

    def to_html(self) -> str:
        """Return a HTML representation of the image gallery: an unordered list with an item per image"""
        from .sanitizer import merge_attributes

        parser = self.parser
        link_renderer = parser.get_link_renderer()
        bad_file_lookup = parser.get_bad_file_lookup()

        if self.per_row > 0:
            maxwidth = self.per_row * (self.widths + self.get_all_padding())
            old_style = self.attribs.get("style", "")
            self.attribs["style"] = f"max-width: {php_number(maxwidth)}px;" + old_style

        attribs = merge_attributes({"class": "gallery mw-gallery-" + self.mode}, self.attribs)

        output = "<ul" + xml_expand_attributes(attribs) + ">"  # Xml::openElement()
        if self.caption:
            output += f"\n\t<li class='gallerycaption'>{self.caption}</li>"

        enable_legacy_media_dom = legacy_media_dom(parser.config)

        # Output each image...
        for nt, text, alt, link, handler_opts, loading, image_options in self.images:
            # "text" means "caption" here
            desc_query = False
            if nt.in_namespace(NS_FILE) and not nt.is_external():
                # Fetch and register the file (file title may be different via hooks)
                img, nt = parser.fetch_file_and_title(nt, {})
            else:
                img = None

            transform_options = {**self.get_thumb_params(img), **handler_opts}
            thumb = img.transform(transform_options) if img else None

            rdfa_type = "mw:File"

            is_bad_file = bool(img and thumb and self.hide_bad_images
                               and bad_file_lookup.is_bad_file(nt.db_key, self.context_title))

            if not img or not thumb or (not enable_legacy_media_dom and thumb.is_error()) or is_bad_file:
                rdfa_type = "mw:Error " + rdfa_type
                if enable_legacy_media_dom:
                    if is_bad_file:
                        thumbhtml = link_renderer.make_known_link(nt, nt.text)
                    else:
                        thumbhtml = htmlspecialchars(img.get_last_error() if img else nt.text)
                else:
                    current_exists = bool(img and img.exists())
                    if current_exists and not thumb:
                        label = "Error creating thumbnail: "
                    elif thumb and thumb.is_error():
                        label = thumb.to_text()
                    else:
                        label = ""
                    thumbhtml = make_broken_image_link_obj(parser, nt, label, "", "", "", False, transform_options,
                                                           current_exists)
                    thumbhtml = raw_element("span", {"typeof": rdfa_type}, thumbhtml)

                thumbhtml = ("\n\t\t\t" + '<div class="thumb" style="height: '
                             + php_number(self.get_thumb_padding() + self.heights) + 'px;">' + thumbhtml + "</div>")
                if not img:
                    parser.add_tracking_category("broken-file-category")
            else:
                vpad = self.get_vpad(self.heights, thumb.get_height())

                # Backwards compat before the image_options existed
                if image_options is None:
                    image_parameters = {
                        "desc-link": True,
                        "desc-query": desc_query,
                        "alt": alt,
                        "custom-url-link": link,
                    }
                else:
                    params = {"alt": alt, "title": image_options["title"]}
                    image_parameters = {**params, **get_image_link_mto_params(image_options, desc_query or "",
                                                                              parser)}

                if loading == LOADING_LAZY:
                    image_parameters["loading"] = "lazy"

                self.adjust_image_parameters(thumb, image_parameters)

                process_responsive_images(parser, img, thumb, transform_options)

                thumbhtml = thumb.to_html(image_parameters, legacy_media_dom=enable_legacy_media_dom)

                if not enable_legacy_media_dom:
                    thumbhtml = raw_element("span", {"typeof": rdfa_type}, thumbhtml)
                else:
                    thumbhtml = raw_element("div", {
                        # Auto-margin centering for block-level elements. Needed now that we have video handlers
                        # since they may emit block- level elements as opposed to simple <img> tags. ref
                        # http://css-discuss.incutio.com/?page=CenteringBlockElement
                        "style": f"margin:{php_number(vpad)}px auto;",
                    }, thumbhtml)

                # Set both fixed width and min-height.
                width = self.get_thumb_div_width(thumb.get_width())
                height = self.get_thumb_padding() + self.heights
                thumbhtml = "\n\t\t\t" + raw_element("div", {
                    "class": "thumb",
                    "style": f"width: {php_number(width)}px;" + (
                        f" height: {php_number(height)}px;"
                        if not enable_legacy_media_dom and self.mode == "traditional" else ""),
                }, thumbhtml)

                # Call parser transform hook
                handler = img.get_handler()
                if handler:
                    handler.parser_transform_hook(parser, img)

            meta = []
            if img:
                if self.show_dimensions:
                    meta.append(htmlspecialchars(img.get_dimensions_string()))
                if self.show_bytes:
                    meta.append(htmlspecialchars(_format_size(img.get_size())))
            elif self.show_dimensions or self.show_bytes:
                meta.append("File missing")  # filemissing
            meta_text = "; ".join(meta)  # Language::semicolonList()
            if meta_text:
                meta_text += "<br />\n"

            textlink = self.get_caption_html(nt, link_renderer) if self.show_filename else ""

            gallery_text = self.wrap_gallery_text(textlink + text + meta_text, thumb)

            gb_width = self.get_gb_width_overwrite(thumb) or php_number(self.get_gb_width(thumb)) + "px"
            # Weird double wrapping (the extra div inside the li) needed due to FF2 bug Can be safely removed if FF2
            # falls completely out of existence
            output += ("\n\t\t" + '<li class="gallerybox" style="width: ' + gb_width + '">'
                       + ('<div style="width: ' + gb_width + '">' if enable_legacy_media_dom else "")
                       + thumbhtml
                       + gallery_text
                       + "\n\t\t"
                       + ("</div>" if enable_legacy_media_dom else "")
                       + "</li>")
        output += "\n</ul>"
        return output

    def get_caption_html(self, nt: Title, link_renderer) -> str:
        """The filename link of a gallery item (showfilename)"""
        caption_length = self.get_caption_length()
        text = nt.text
        if isinstance(caption_length, int) and not isinstance(caption_length, bool):
            text = _truncate_for_visual(text, caption_length)
        return link_renderer.make_known_link(nt, text, {
            "class": "galleryfilename" + (" galleryfilename-truncate" if caption_length is True else ""),
        }) + "\n"

    def wrap_gallery_text(self, gallery_text: str, thumb) -> str:
        """Add the wrapper html around the thumb's caption"""
        # ATTENTION: The newline after <div class="gallerytext"> is needed to accommodate htmltidy which in version
        # 4.8.6 generated crackpot html in its absence, see: https://phabricator.wikimedia.org/T3765
        return "\n\t\t\t" + '<div class="gallerytext">' + "\n" + gallery_text + "\n\t\t\t</div>"

    def get_thumb_padding(self):
        """How much padding the thumb has between the image and the inner div that contains the border. This is
        for both vertical and horizontal padding. (divided by 2 in the case of vertical padding)."""
        return 30

    def get_gb_padding(self):
        """The padding between the image's border and the gallerybox."""
        return 5

    def get_gb_borders(self):
        """Get how much extra space the borders around the image takes up. For this mode, it is 2px on both
        sides, so 8 for the 4 sides"""
        return 8

    def get_caption_length(self):
        return self.caption_length

    def get_all_padding(self):
        """Get total padding."""
        return self.get_thumb_padding() + self.get_gb_padding() + self.get_gb_borders()

    def get_vpad(self, box_height, thumb_height):
        """Get vertical padding for a thumbnail. Generally this is the total height minus how high the thumb is."""
        return _php_divide(self.get_thumb_padding() + box_height - thumb_height, 2)

    def get_thumb_params(self, img) -> dict:
        """Get the transform parameters for a thumbnail."""
        return {"width": self.widths, "height": self.heights}

    def get_thumb_div_width(self, thumb_width):
        """Get the width of the inner div that contains the thumbnail in question. This is the div with the class
        of "thumb"."""
        return self.widths + self.get_thumb_padding()

    def get_gb_width(self, thumb):
        """Computed width of gallerybox <li>."""
        return self.widths + self.get_thumb_padding() + self.get_gb_padding()

    def get_gb_width_overwrite(self, thumb):
        """Allows overwriting the computed width of the gallerybox <li> with a string, like '100%'."""
        return False

    def adjust_image_parameters(self, thumb, image_parameters: dict) -> None:
        """Adjust the image parameters for a thumbnail. Used by a subclass to insert extra high resolution images."""


class NolinesImageGallery(TraditionalImageGallery):

    def get_thumb_padding(self):
        return 0

    def get_gb_borders(self):
        # This accounts for extra space between <li> elements.
        return 4

    def get_vpad(self, box_height, thumb_height):
        return 0


class PackedImageGallery(TraditionalImageGallery):
    SCALE_FACTOR = 1.5

    def __init__(self, mode: str = "traditional", options: Optional[dict] = None):
        super().__init__(mode, options)
        # Does not support per row option.
        self.per_row = 0

    def get_vpad(self, box_height, thumb_height):
        return (self.get_thumb_padding() + box_height - thumb_height / self.SCALE_FACTOR) / 2

    def get_thumb_padding(self):
        return 0

    def get_gb_padding(self):
        return 2

    def get_thumb_params(self, img) -> dict:
        if img and img.get_media_type() == MEDIATYPE_AUDIO:
            width = self.widths
        else:
            # We want the width not to be the constraining factor, so use random big number.
            width = self.heights * 10 + 100
        # self::SCALE_FACTOR so the js has some room to manipulate sizes.
        return {"width": width * self.SCALE_FACTOR, "height": self.heights * self.SCALE_FACTOR}

    def get_thumb_div_width(self, thumb_width):
        # Require at least 60px wide, so caption is wide enough to work.
        if thumb_width < 60 * self.SCALE_FACTOR:
            thumb_width = 60 * self.SCALE_FACTOR
        return thumb_width / self.SCALE_FACTOR + self.get_thumb_padding()

    def get_gb_width(self, thumb):
        thumb_width = thumb.get_width() if thumb else self.widths * self.SCALE_FACTOR
        return self.get_thumb_div_width(thumb_width) + self.get_gb_padding()

    def adjust_image_parameters(self, thumb, image_parameters: dict) -> None:
        # Re-adjust back to normal size.
        image_parameters["override-width"] = float(math.ceil(thumb.get_width() / self.SCALE_FACTOR))
        image_parameters["override-height"] = float(math.ceil(thumb.get_height() / self.SCALE_FACTOR))

    def set_per_row(self, num) -> None:
        pass


class PackedOverlayImageGallery(PackedImageGallery):
    """Packed overlay image gallery. All images adjusted to be same height and image caption being placed over top
    of image."""

    def wrap_gallery_text(self, gallery_text: str, thumb) -> str:
        # If we have no text, do not output anything to avoid ugly white overlay.
        if gallery_text.strip(" \t\n\r\0\x0b") == "":
            return ""
        thumb_width = self.get_gb_width(thumb) - self.get_thumb_padding() - self.get_gb_padding()
        caption_width = math.ceil(thumb_width - 20)
        outer_wrapper = '<div class="gallerytextwrapper" style="width: ' + php_number(float(caption_width)) + 'px">'
        return ("\n\t\t\t" + outer_wrapper + '<div class="gallerytext">' + "\n" + gallery_text
                + "\n\t\t\t</div></div>")


class PackedHoverImageGallery(PackedOverlayImageGallery):
    """Same as Packed except different CSS is applied to make the caption only show up on hover."""


class SlideshowImageGallery(TraditionalImageGallery):
    """The traditional gallery with a data-showthumbnails attribute; its interface comes from client-side script
    (the ResourceLoader module of getModules(), not ported)."""

    def __init__(self, mode: str = "traditional", options: Optional[dict] = None):
        super().__init__(mode, options)
        # Does not support per row option.
        self.per_row = 0

    def set_additional_options(self, params: dict) -> None:
        self.attribs["data-showthumbnails"] = "showthumbnails" in params


# ImageGalleryBase::loadModes()
MODE_MAPPING = {
    "traditional": TraditionalImageGallery,
    "nolines": NolinesImageGallery,
    "packed": PackedImageGallery,
    "packed-hover": PackedHoverImageGallery,
    "packed-overlay": PackedOverlayImageGallery,
    "slideshow": SlideshowImageGallery,
}


def _php_divide(a, b):
    """PHP's / : an int if the division is exact, a float otherwise"""
    if isinstance(a, int) and isinstance(b, int) and a % b == 0:
        return a // b
    return a / b


def _format_size(size: int) -> str:
    """Language::formatSize() in English"""
    units = ["bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    index = 0
    size = float(size)
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    text = f"{size:.0f}" if index == 0 else f"{size:.2f}".rstrip("0").rstrip(".")
    return f"{text} {units[index]}"


def _truncate_for_visual(text: str, length: int) -> str:
    """Language::truncateForVisual() (character count, '...' ellipsis)"""
    if len(text) <= length:
        return text
    return text[:max(length - 1, 0)] + "…"


def render_image_gallery(parser, text: str, params: dict) -> str:
    """Parser::renderImageGallery(): render an image gallery from a text with one line per image. text labels may
    be given by using |-style alternative text. E.g.
      Image:one.jpg|The number "1"
      Image:tree.jpg|A tree
    given as text will return the HTML of a gallery with two images, labeled 'The number "1"' and 'A tree'."""
    from .sanitizer import validate_tag_attributes
    from .stringutils import delimiter_explode

    mode = params.get("mode", False)
    try:
        ig = ImageGalleryBase.factory(mode)
    except ImageGalleryClassNotFoundException:
        # If invalid type set, fallback to default.
        ig = ImageGalleryBase.factory(False)

    ig.set_context_title(parser.get_title())
    ig.set_show_bytes(False)
    ig.set_show_dimensions(False)
    ig.set_show_filename(False)
    ig.set_parser(parser)
    ig.set_hide_bad_images()
    ig.set_attributes(validate_tag_attributes(params, "ul", config=parser.config))

    ig.set_show_filename("showfilename" in params)
    if "caption" in params:
        # NOTE: We aren't passing a frame here or below. Frame info is currently opaque to Parsoid, which acts on
        # OT_PREPROCESS. See T107332#4030581
        caption = parser.recursive_tag_parse(params["caption"])
        ig.set_caption_html(caption)
    if "perrow" in params:
        ig.set_per_row(params["perrow"])
    if "widths" in params:
        ig.set_widths(params["widths"])
    if "heights" in params:
        ig.set_heights(params["heights"])
    ig.set_additional_options(params)

    for line in text.split("\n"):
        # match lines like these:
        # Image:someimage.jpg|This is some image
        m = re.match(r"^([^|]+)(\|(.*))?$", line)
        # Skip empty lines
        if not m:
            continue
        target = m.group(1)
        if "%" in m.group(0):
            target = unquote(target, errors="surrogateescape")
        title = Title.new_from_text(target, NS_FILE, site=parser.site)
        if title is None:
            # Bogus title. Ignore these so we don't bomb out later.
            continue

        # We need to get what handler the file uses, to figure out parameters. Don't register it now, as
        # TraditionalImageGallery does that later.
        file = parser.fetch_file_no_register(title, {})
        handler = file.get_handler() if file else None

        param_map = {"img_alt": "gallery-internal-alt", "img_link": "gallery-internal-link"}
        if handler:
            for key, value in handler.get_param_map().items():
                param_map.setdefault(key, value)
            # We don't want people to specify per-image widths. Additionally the width parameter would need special
            # casing anyhow.
            param_map.pop("img_width", None)

        mw_array = parser.magic_words.new_array(list(param_map))

        label = ""
        alt = ""
        handler_options: dict = {}
        image_options: dict = {}
        has_alt = False

        if m.group(3) is not None:
            # look for an |alt= definition while trying not to break existing captions with multiple pipes (|) in
            # it, until a more sensible grammar is defined for images in galleries

            # FIXME: Doing recursiveTagParse at this stage, and the trim before splitting on '|' is a bit odd, and
            # different from makeImage.
            matches3 = parser.recursive_tag_parse(m.group(3).strip(" \t\n\r\0\x0b"))
            # Protect LanguageConverter markup
            parameter_matches = delimiter_explode("-{", "}-", "|", matches3, True)

            for parameter_match in parameter_matches:
                magic_name, match = mw_array.match_variable_start_to_end(parameter_match)
                if not magic_name:
                    # Last pipe wins.
                    label = parameter_match
                    continue

                param_name = param_map[magic_name]
                if param_name == "gallery-internal-alt":
                    has_alt = True
                    alt = parser.strip_alt_text(match, False)
                elif param_name == "gallery-internal-link":
                    link_value = parser.strip_alt_text(match, False)
                    if re.match(r"^-\{R\|(.*)\}-$", link_value):
                        # Result of LanguageConverter::markNoConversion invoked on an external link.
                        link_value = link_value[4:-2]
                    type_, target = parser.parse_link_parameter(link_value)
                    if type_:
                        if type_ == "no-link":
                            target = True
                        image_options[type_] = target
                else:
                    # Must be a handler specific parameter.
                    if handler.validate_param(param_name, match):
                        handler_options[param_name] = match
                    else:
                        # Guess not, consider it as caption.
                        label = parameter_match

        # Match makeImage when !$hasVisibleCaption
        if not has_alt:
            if label != "":
                alt = parser.strip_alt_text(label, False)
            else:
                alt = title.text
        image_options["title"] = parser.strip_alt_text(label, False)

        ig.add(title, label, alt, "", handler_options, LOADING_DEFAULT, image_options)
    return ig.to_html()

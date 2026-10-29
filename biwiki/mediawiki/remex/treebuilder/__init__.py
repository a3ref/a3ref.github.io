# Ported from RemexHtml 3.0.2 src/TreeBuilder/ (https://github.com/wikimedia/remex-html),
# (C) 2016 Wikimedia Foundation. MIT license: see biwiki/mediawiki/remex/LICENSE.
# Changed by a3ref contributors on 2026-10-30: translated to Python; the insertion modes are grouped into a few
# modules.
"""Tree construction: tree mutation events from token events (namespace Wikimedia\\RemexHtml\\TreeBuilder)."""
# The dispatcher is imported first: it imports the insertion modes, which import it back for its constants.
from .dispatcher import Dispatcher  # isort: skip
from .active_formatting_elements import ActiveFormattingElements, TemplateModeStack
from .body_modes import InBody, InPre, InTextarea, Text
from .document_modes import (AfterAfterBody, AfterAfterFrameset, AfterBody, AfterFrameset, AfterHead, BeforeHead,
                             BeforeHtml, InFrameset, InHead, InHeadNoscript, Initial)
from .element import Element, FormattingElement, Marker
from .foreign_attributes import ForeignAttributes
from .in_foreign_content import InForeignContent
from .insertion_mode import InsertionMode
from .select_template_modes import InSelect, InSelectInTable, InTemplate
from .stack import CachingStack, SimpleStack, Stack, TreeBuilderError
from .table_modes import InCaption, InCell, InColumnGroup, InRow, InTable, InTableBody, InTableText
from .tracer import DispatchTracer, TraceFormatter, TreeMutationTracer
from .tree_builder import TreeBuilder
from .tree_handler import NullTreeHandler, RelayTreeHandler, TreeHandler

__all__ = [
    "ActiveFormattingElements", "AfterAfterBody", "AfterAfterFrameset", "AfterBody", "AfterFrameset", "AfterHead",
    "BeforeHead", "BeforeHtml", "CachingStack", "DispatchTracer", "Dispatcher", "Element", "ForeignAttributes",
    "FormattingElement", "InBody", "InCaption", "InCell", "InColumnGroup", "InForeignContent", "InFrameset",
    "InHead", "InHeadNoscript", "InPre", "InRow", "InSelect", "InSelectInTable", "InTable", "InTableBody",
    "InTableText", "InTemplate", "InTextarea", "Initial", "InsertionMode", "Marker", "NullTreeHandler",
    "RelayTreeHandler", "SimpleStack", "Stack", "TemplateModeStack", "Text", "TraceFormatter", "TreeBuilder",
    "TreeBuilderError", "TreeHandler", "TreeMutationTracer",
]

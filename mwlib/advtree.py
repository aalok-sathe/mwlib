# Copyright (c) 2007-2008 PediaPress GmbH
# See README.txt for additional licensing information.

"""
The parse tree generated by the parser is a 1:1 representation of the mw-markup.
Unfortunally these trees have some flaws if used to geenerate derived documents.

This module seeks to rebuild the parstree
to be:
 * more logical markup
 * clean up the parse tree
 * make it more accessible
 * allow for validity checks
 * implement rebuilding strategies

Usefull Documentation:
http://en.wikipedia.org/wiki/Wikipedia:Don%27t_use_line_breaks
http://meta.wikimedia.org/wiki/Help:Advanced_editing
http://meta.wikimedia.org/wiki/Help:HTML_in_wikitext
"""

import weakref
from mwlib.parser import Magic, Math,  _VListNode, Ref, Link, URL, NamedURL # not used but imported
from mwlib.parser import CategoryLink, SpecialLink, Caption, LangLink # not used but imported
from mwlib.parser import ArticleLink, InterwikiLink, NamespaceLink
from mwlib.parser import Item, ItemList,  Node, Table, Row, Cell, Paragraph, PreFormatted
from mwlib.parser import Section, Style, TagNode, Text, Timeline
from mwlib.parser import  ImageLink, Article, Book, Chapter
import copy
from mwlib.log import Log

log = Log("advtree")


def _idIndex(lst, el):
    """Return index of first appeareance of element el in list lst"""
    
    for i, e in enumerate(lst):
        if e is el:
            return i
    raise ValueError('element %r not found' % el)

def debug(method): # use as decorator
    def f(self, *args, **kargs):
        log("\n%s called with %r %r" % (method.__name__, args, kargs))
        log("on %r attrs:%r style:%r" % (self, self.attributes, self.style) )
        p = self
        while p.parent:
            p = p.parent
            log("%r" % p)
        return method(self, *args, **kargs)
    return f


class AdvancedNode:
    """Mixin Class that extends Nodes so they become easier accessible.

    Allows to traverse the tree in any direction and 
    build derived convinience functions
   """

    _parentref = None # weak referece to parent element
    isblocknode = False

    def copy(self):
        "return a copy of this node and all its children"
        n = copy.copy(self)
        n.children = []
        n._parentref = None
        for c in self:
            n.appendChild(c.copy())
        return n


    def moveto(self, targetnode, prefix=False): #FIXME: bad name. rename to moveBehind, and create method moveBefore
        """Move this node behind the target node.

        If prefix is true, move before the target node.
        """
        
        if self.parent:
            self.parent.removeChild(self)
        tp = targetnode.parent
        idx = _idIndex(tp.children, targetnode)
        if not prefix:
            idx+=1
        tp.children = tp.children[:idx] + [self] + tp.children[idx:]
        self._parentref = weakref.ref(tp)

    def hasChild(self, c):
        """Check if node c is child of self"""
        try:
            _idIndex(self.children, c)
            assert c.parent is self
            return True
        except ValueError:
            return False
        
    def appendChild(self, c):
        self.children.append(c)
        c._parentref = weakref.ref(self)

    def removeChild(self, c):
        self.replaceChild(c, [])
        assert c.parent is None

    def replaceChild(self, c, newchildren = []):
        """Remove child node c and replace with newchildren if given."""

        assert self.hasChild(c), 'Error, unknown child'
        idx = _idIndex(self.children, c)
        self.children = self.children[:idx] + self.children[idx+1:]
        c._parentref = None
        assert not self.hasChild(c)
        if newchildren:
            self.children = self.children[:idx] + newchildren + self.children[idx:]
            for nc in newchildren:
                nc._parentref = weakref.ref(self)

    def getParents(self):
        """Return list of parent nodes up to the root node.

        The returned list starts with the root node.
        """
        if self.parent:
            return self.parent.getParents() + [self.parent]
        else:
            return []

    def getParent(self):
        """Return the parent node or raise weakref.ReferenceError"""
        if not self._parentref:
            return None
        x = self._parentref()
        if not x:
            raise weakref.ReferenceError
        return x

    def getLevel(self):
        """Returns the number of nodes of same class in parents"""
        return [p.__class__ for p in self.getParents()].count(self.__class__)

   
    def getParentNodesByClass(self, klass): #FIXME: rename to getParentsByClass
        """returns parents w/ klass"""
        return [p for p in self.parents if p.__class__ == klass]

    def getChildNodesByClass(self, klass): #FIXME: rename to getChildrenByClass
        """returns all children  w/ klass"""
        return [p for p in self.getAllChildren() if p.__class__ == klass]

    def getAllChildren(self):
        """don't confuse w/ Node.allchildren() which returns allchildren + self"""
        for c in self.children:
            yield c
            for x in c.getAllChildren():
                yield x        
        
    def getSiblings(self):
        """Return all siblings WITHOUT self"""
        return [c for c in self.getAllSiblings() if c is not self]

    def getAllSiblings(self):
        """Return all siblings plus self"""
        if self.parent:
            return self.parent.children
        return []

    def getPrevious(self):
        """Return previous sibling"""
        s = self.getAllSiblings()
        try:
            idx = _idIndex(s,self)
        except ValueError:
            return None
        if idx -1 <0:
            return None
        else:
            return s[idx-1]

    def getNext(self):
        """Return next sibling"""
        s = self.getAllSiblings()
        try:
            idx = _idIndex(s,self)
        except ValueError:
            return None
        if idx+1 >= len(s):
            return None
        else:
            return s[idx+1]

    def getLast(self): #FIXME might return self. is this intended?
        """Return last sibling"""
        s = self.getAllSiblings()
        if s:
            return s[-1]

    def getFirst(self): #FIXME might return self. is this intended?
        """Return first sibling"""
        s = self.getAllSiblings()
        if s:
            return s[0]

    def getLastChild(self):
        """Return last child of this node"""
        if self.children:
            return self.children[-1]

    def getFirstChild(self):
        "Return first child of this node"
        if self.children:
            return self.children[0]

    def getFirstLeaf(self, callerIsSelf=True):
        """Return 'first' child that has no children itself"""
        if self.children:
            if self.__class__ == Section: # first kid of a section is its caption
                if len(self.children) == 1:
                    return None
                else:
                    return self.children[1].getFirstLeaf(callerIsSelf=False)
            else:
                return self.children[0].getFirstLeaf(callerIsSelf=False)
        else:
            if callerIsSelf:
                return None
            else:
                return self

    def getLastLeaf(self, callerIsSelf=True):
        """Return 'last' child that has no children itself"""
        if self.children:
            return self.children[-1].getFirstLeaf(callerIsSelf=False)
        else:
            if callerIsSelf:
                return None
            else:
                return self

    def getAllDisplayText(self, amap = None):
        "Return all text that is intended for display"
        text = []
        if not amap:
            amap = {Text:"caption", Link:"target", URL:"caption", Math:"caption", ImageLink:"caption" }
        for n in self.allchildren():
            access = amap.get(n.__class__, "")
            if access:
                text.append( getattr(n, access) )
        alltext = [t for t in text if t]
        if alltext:
            return u''.join(alltext)
        else:
            return ''
    
    def getStyle(self):
        if not self.attributes:
            return {}
        style =  self.attributes.get('style', {}) # THIS IS BROKEN
        return style

    def getAttributes(self):
        """ Return dict with node attributes (e.g. class, style, colspan etc.)"""
        attrs = getattr(self, 'vlist', {})
        for n in ("colspan", "rowspan"): # col, row span attributes 
            v = attrs.get(n)
            if v is not None:
                if isinstance(v, (str, unicode)) and v.isdigit():
                    attrs[n] = int(v)
                elif not isinstance(v, int):
                    attrs[n] = 1 # some default
                attrs[n] = max(attrs[n], 1)
        return attrs


    def isVisible(self):
        """Return True if node is visble. Used to detect hidden elements."""
        if self.style.get('display', '').lower() == 'none':
            return False
        if self.style.get('visibility','').lower() == 'hidden':
            return False
        return True

    
    style = property(getStyle)
    attributes = property(getAttributes)
    visible = property(isVisible)
    
    parent = property(getParent)
    parents = property(getParents)
    next = property(getNext)
    previous = property(getPrevious)
    siblings = property(getSiblings)
    last = property(getLast)
    first = property(getFirst)
    lastchild = property(getLastChild)
    firstchild = property(getFirstChild)
    


# --------------------------------------------------------------------------
# MixinClasses w/ special behaviour
# -------------------------------------------------------------------------

class AdvancedTable(AdvancedNode):    
    @property 
    def rows(self):
        return [r for r in self if r.__class__ == Row]

    @property 
    def numcols(self):
        max_cols = 0
        for row in self.children:
            cols = sum([cell.attributes.get('colspan', 1) for cell in row.children])
            max_cols = max(max_cols, cols)
        return max_cols

        
class AdvancedRow(AdvancedNode):    
    @property 
    def cells(self):
        return [c for c in self if c.__class__ == Cell]


class AdvancedCell(AdvancedNode):
    @property    
    def colspan(self, attr="colspan"):
        # returns None if there is no valid colspan e.g. colspan="one"
        c = self.vlist.get(attr, None)
        if c is not None and (isinstance(c,int) or (isinstance(c, (str, unicode)) and c.isdigit())):
            return max(1,int(c))

    @property
    def rowspan(self):
        return self.colspan(attr="rowspan")



class AdvancedSection(AdvancedNode):
    def getSectionLevel(self):
        return 1 + self.getLevel()

class AdvancedImageLink(AdvancedNode):
    isblocknode = property ( lambda s: not s.isInline() )
    
class AdvancedMath(AdvancedNode):
    @property
    def isblocknode(self):
        if self.caption.strip().startswith("\\begin{align}")  or \
                self.caption.strip().startswith("\\begin{alignat}"):
            return True
        return False

       

# --------------------------------------------------------------------------
# Missing as Classes derived from parser.Style
# -------------------------------------------------------------------------

class Italic(Style, AdvancedNode):
    _tag = "i"

class Emphasized(Style, AdvancedNode):
    _tag = "em"

class Strong(Style, AdvancedNode):
    _tag = "strong"

class DefinitionList(Style, AdvancedNode):
    _tag = "dl"

class DefinitionTerm(Style, AdvancedNode):
    _tag = "dt"

class DefinitionDescription(Style, AdvancedNode):
    _tag = "dd"

class Blockquote(Style, AdvancedNode):
    "margins to left &  right"
    _tag = "blockquote"
    
class Indented(Style, AdvancedNode):
    "margin to the left"
    def getIndentLevel(self):
        return self.caption.count(":")
    indentlevel = property(getIndentLevel)

class Overline(Style, AdvancedNode):
    _style = "overline"

class Underline(Style, AdvancedNode):
    _style = "u"

class Sub(Style, AdvancedNode):
    _style = "sub"
    _tag = "sub"

class Sup(Style, AdvancedNode):
    _style = "sup"
    _tag = "sup"

class Small(Style, AdvancedNode):
    _style = "small"
    _tag = "small"

class Big(Style, AdvancedNode):
    _style = "big"
    _tag = "big"

class Cite(Style, AdvancedNode):
    _style = "cite"
    _tag = "cite"

class Var(TagNode, AdvancedNode): 
    _tag = "var"
    _style = "var"



_styleNodeMap = dict( (k._style,k) for k in [Overline, Underline, Sub, Sup, Small, Big, Cite,Var] )

# --------------------------------------------------------------------------
# Missing as Classes derived from parser.TagNode
# http://meta.wikimedia.org/wiki/Help:HTML_in_wikitext
# -------------------------------------------------------------------------


class Source(TagNode, AdvancedNode):
    _tag = "source"

class Code(TagNode, AdvancedNode):
    _tag = "code"

class BreakingReturn(TagNode, AdvancedNode):
    _tag = "br"

class HorizontalRule(TagNode, AdvancedNode):
    _tag = "hr"

class Index(TagNode, AdvancedNode):
    _tag = "index"

class Teletyped(TagNode, AdvancedNode):
    _tag = "tt"

class Reference(TagNode, AdvancedNode):
    _tag = "ref"

class ReferenceList(TagNode, AdvancedNode):
    _tag = "references"

class Gallery(TagNode, AdvancedNode):
    _tag = "gallery"

class Center(TagNode, AdvancedNode):
    _tag = "center"

class Div(TagNode, AdvancedNode):
    _tag = "div"

class Span(TagNode, AdvancedNode): # span is defined as inline node which is in theory correct. 
    _tag = "span"

class Strike(TagNode,AdvancedNode):
    _tag = "strike"

class ImageMap(TagNode, AdvancedNode): # defined as block node, maybe incorrect
    _tag = "imagemap"

class Ruby(TagNode, AdvancedNode): 
    _tag = "ruby"

class RubyBase(TagNode, AdvancedNode):
    _tag = "rb"

class RubyParentheses(TagNode, AdvancedNode):
    _tag = "rp"

class RubyText(TagNode, AdvancedNode): 
    _tag = "rt"

class Deleted(TagNode, AdvancedNode): 
    _tag = "del"

class Inserted(TagNode, AdvancedNode): 
    _tag = "ins"

class TableCaption(TagNode, AdvancedNode): 
    _tag = "caption"

    
_tagNodeMap = dict( (k._tag,k) for k in [Source, Code, BreakingReturn, HorizontalRule, Index, Teletyped, Reference, ReferenceList, Gallery, Center, Div, Span, Strike, ImageMap, Ruby, RubyBase, RubyText, Deleted, Inserted, TableCaption] )
_styleNodeMap["s"] = Strike # Special Handling for deprecated s style


# --------------------------------------------------------------------------
# BlockNode separation for AdvancedNode.isblocknode
# -------------------------------------------------------------------------

"""
For writers it is usefull to know whether elements are inline (within a paragraph) or not.
We define list for blocknodes, which are used in AdvancedNode as:

AdvancedNode.isblocknode

Image depends on result of Image.isInline() see above

Open Issues: Math, Magic, (unknown) TagNode 

"""
_blockNodes = (Blockquote, Book, Chapter, Article, Section, Paragraph, Div, Center,
               PreFormatted, Cell, Row, Table, Item, BreakingReturn,
               ItemList, Timeline, Cite, HorizontalRule, Gallery, Indented, 
               DefinitionList, DefinitionTerm, DefinitionDescription, ReferenceList, Source)

for k in _blockNodes:  
  k.isblocknode = True



# --------------------------------------------------------------------------
# funcs for extending the nodes
# -------------------------------------------------------------------------

def mixIn(pyClass, mixInClass, makeFirst=False):
  if mixInClass not in pyClass.__bases__:
    if makeFirst:
      pyClass.__bases__ = (mixInClass,) + pyClass.__bases__
    else:
      pyClass.__bases__ += (mixInClass,)

def extendClasses(node):
    for c in node.children[:]:
        extendClasses(c)
        c._parentref = weakref.ref(node)            

# Nodes we defined above and that are separetly handled in extendClasses
_advancedNodesMap = {Section: AdvancedSection, ImageLink:AdvancedImageLink, 
                     Math:AdvancedMath, Cell:AdvancedCell, Row:AdvancedRow, Table:AdvancedTable}
mixIn(Node, AdvancedNode)
for k, v in _advancedNodesMap.items():
    mixIn(k,v)
    
# --------------------------------------------------------------------------
# Functions for fixing the parse tree
# -------------------------------------------------------------------------

def fixTagNodes(node):
    """Detect known TagNodes and and transfrom to appropriate Nodes"""
    for c in node.children:
        if c.__class__ == TagNode:
            if c.caption in _tagNodeMap:
                c.__class__ = _tagNodeMap[c.caption]
            elif c.caption in ("h1", "h2", "h3", "h4", "h5", "h6"): # FIXME
                # NEED TO MOVE NODE IF IT REALLY STARTS A SECTION
                c.__class__ = Section 
                mixIn(c.__class__, AdvancedSection)
                c.level = int(c.caption[1])
                c.caption = ""
            else:
                log.warn("fixTagNodes, unknowntagnode %r" % c)
        fixTagNodes(c)


def fixStyleNode(node): #FIXME: rename to fixStyleNode or something like that
    """
    parser.Style Nodes are mapped to logical markup
    detection of DefinitionList depends on removeNodes
    and removeNewlines
    """
    if not node.__class__ == Style:
        return
    if node.caption == "''": 
        node.__class__ = Emphasized
        node.caption = ""
    elif node.caption=="'''''":
        node.__class__ = Strong
        node.caption = ""
        em = Emphasized("''")
        for c in node.children:
            em.appendChild(c)
        node.children = []
        node.appendChild(em)
    elif node.caption == "'''":
        node.__class__ = Strong
        node.caption = ""
    elif node.caption == ";": 
        # this starts a definition list ? DL [DT->DD, ...]
        # check if previous node is DefinitionList, if not create one
        if node.previous.__class__ == DefinitionList:
            node.__class__ = DefinitionTerm
            node.moveto(node.previous.lastchild)
        else:
            node.__class__ = DefinitionList
            dt = DefinitionTerm()
            for c in node.children:
                dt.appendChild(c)
            node.children = []
            node.appendChild(dt)
    elif node.caption.startswith(":"): 
        if node.previous.__class__ == DefinitionList:
            node.__class__ = DefinitionDescription
            node.moveto(node.previous.lastchild)
            node.caption = ""
        else:
            node.__class__ = Indented
    elif node.caption == '-':
        node.__class__ = Blockquote
        node.caption = ''
    elif node.caption in _styleNodeMap:
        node.__class__ = _styleNodeMap[node.caption]
        node.caption = ""
    else:
        log.warn("fixStyle, unknownstyle %r" % node)
        return node
    
    return node

def fixStyleNodes(node): #FIXME: rename to fixStyleNodes or something like that
    if node.__class__ == Style:
        fixStyleNode(node)
    for c in node.children[:]:
        fixStyleNodes(c)


def removeNodes(node):
    """
    the parser generates empty Node elements that do 
    nothing but group other nodes. we remove them here
    """
    if node.__class__ == Node:
        # first child of section groups heading text - grouping Node must not be removed
        if not (node.previous == None and node.parent.__class__ == Section): 
            node.parent.replaceChild(node, node.children)
            
    for c in node.children[:]:
        removeNodes(c)

def removeNewlines(node):
    """
    remove newlines, tabs, spaces if we are next to a blockNode
    """
    if node.__class__ == Text and not node.getParentNodesByClass(PreFormatted) and not node.getParentNodesByClass(Source) and node.caption:
        if node.caption.strip() == u"":
            prev = node.previous or node.parent # previous sibling node or parentnode 
            next = node.next or node.parent.next
            if not next or next.isblocknode or not prev or prev.isblocknode: 
                assert not node.children
                np = node.parent
                node.parent.removeChild(node)    
                assert node.parent is None
                assert not np.hasChild(node)
        node.caption = node.caption.replace("\n", " ")
      
    for c in node.children[:]:
        removeNewlines(c)            


def buildAdvancedTree(root): # USE WITH CARE
    """
    extends and cleans parse trees
    do not use this funcs without knowing whether these 
    Node modifications fit your problem
    """
#    _validateParserTree(root)
    extendClasses(root) 
    fixTagNodes(root)
    removeNodes(root)
    removeNewlines(root)
    fixStyleNodes(root) 
    _validateParents(root)       


def _validateParserTree(node, parent=None):
    # helper to assert tree parent link consistency
    if parent is not None:
        _idIndex(parent.children, node) # asserts it occures only once
    for c in node:
        _idIndex(node.children, c) # asserts it occures only once
        assert c in node.children
        _validateParserTree(c, node)


def _validateParents(node, parent=None):
    # helper to assert tree parent link consistency
    if parent is not None:
        assert parent.hasChild(node)
    else:
        assert node.parent is None      
    for c in node:
        assert node.hasChild(c)
        _validateParents(c, node)
        


def getAdvTree(fn):
    from mwlib.dummydb import DummyDB
    from mwlib.uparser import parseString
    db = DummyDB()
    input = unicode(open(fn).read(), 'utf8')
    r = parseString(title=fn, raw=input, wikidb=db)
    buildAdvancedTree(r)
    return r

def simpleparse(raw):    # !!! USE FOR DEBUGGING ONLY !!! 
    import sys
    from mwlib import dummydb, parser
    from mwlib.uparser import parseString
    input = raw.decode('utf8')
    r = parseString(title="title", raw=input, wikidb=dummydb.DummyDB())
    buildAdvancedTree(r)
    parser.show(sys.stdout, r, 0)
    return r


# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.abspath('../'))

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.viewcode',
]

autoclass_content = 'init'

templates_path = ['_templates']
source_suffix = '.rst'
master_doc = 'index'

project = u'chdkptp.py'
copyright = u'2014, Johannes Baiter'
version = '0.1'
release = '0.1'

exclude_patterns = ['_build']
pygments_style = 'sphinx'

html_theme = 'default'
html_static_path = ['_static']
htmlhelp_basename = 'chdkptppydoc'

latex_elements = {
    'preamble': '',
}
latex_documents = [
    ('index', 'chdkptppy.tex', u'chdkptp.py Documentation',
     u'Johannes Baiter', 'manual'),
]

man_pages = [
    ('index', 'chdkptppy', u'chdkptp.py Documentation',
     [u'Johannes Baiter'], 1)
]

texinfo_documents = [
    ('index', 'chdkptppy', u'chdkptp.py Documentation',
     u'Johannes Baiter', 'chdkptppy', 'One line description of project.',
     'Miscellaneous'),
]

intersphinx_mapping = {'http://docs.python.org/': None}

# CrossTalk briefing typography

The native Template renderer owns the paper cover, author metadata, DOI-status
line, contents and final PDF. These project declarations set the page geometry
and the black, white, gray and red presentation. The three generated graphical
abstract pages follow the cover. Their actual placement and all glyph bounds
require verification in the rendered PDF.

```latex
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{geometry}
\geometry{margin=0.35in,footskip=0.18in}
\usepackage{caption}
\usepackage{microtype}
\usepackage{etoolbox}
\AtBeginDocument{%
  \apptocmd{\thebibliography}{\small\interlinepenalty=10000\relax}{}{%
    \PackageError{CrossTalk}{Unable to keep bibliography entries together}{}%
  }%
}
\definecolor{CrossTalkRed}{HTML}{B00020}
\definecolor{CrossTalkGray}{HTML}{777777}
\captionsetup{font={small,sf},labelfont=bf,labelsep=period,skip=5pt}
\renewcommand{\familydefault}{\sfdefault}
\setlength{\emergencystretch}{3em}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.35em}
\raggedbottom
\let\CrossTalkOriginalContents\tableofcontents
\renewcommand{\tableofcontents}{%
  \input{../manuscript/_crosstalk_frontmatter.inc}%
  \CrossTalkOriginalContents%
}
```

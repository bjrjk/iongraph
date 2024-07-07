# Axel '0vercl0k' Souchet - 10 May 2019
# Jack Ren - 2024.05
from __future__ import print_function
import sys
import os
import subprocess
import argparse
import json
import cgi
import zlib
import shutil

folder_out = 'iongraph-out'

# Stolen from https://github.com/sstangl/iongraph/blob/master/iongraph
# with a handful of customizations.
def quote(s):
    return '"%s"' % str(s)

# Simple classes for the used subset of GraphViz' Dot format.
# There are more complicated constructors out there, but they all
# pull in annoying dependencies (and are annoying dependencies themselves).
class GraphWidget:
    def __init__(self):
        self.name = ''
        self.props = {}

    def addprops(self, propdict):
        for p in propdict:
            self.props[p] = propdict[p]


class Node(GraphWidget):
    def __init__(self, name):
        GraphWidget.__init__(self)
        self.name = str(name)

class Edge(GraphWidget):
    def __init__(self, nfrom, nto):
        GraphWidget.__init__(self)
        self.nfrom = str(nfrom)
        self.nto = str(nto)

class Graph(GraphWidget):
    def __init__(self, name, func, type):
        GraphWidget.__init__(self)
        self.name = name
        self.func = func
        self.type = str(type)
        self.props = {}
        self.nodes = []
        self.edges = []

    def addnode(self, n):
        self.nodes.append(n)

    def addedge(self, e):
        self.edges.append(e)

    def writeprops(self, f, o):
        if len(o.props) == 0:
            return

        print('[', end=' ', file=f)
        for p in o.props:
            print(str(p) + '=' + str(o.props[p]), end=' ', file=f)
        print(']', end=' ', file=f)

    def write(self, f):
        print(self.type, '{', file=f)

        # Use the pass name as the graph title (at the top).
        print('labelloc = t;', file=f)
        print('labelfontsize = 30;', file=f)
        print('label = "%s -  %s";' % (self.func['name'], self.name), file=f)

        # Output graph properties.
        for p in self.props:
            print('  ' + str(p) + '=' + str(self.props[p]), file=f)
        print('', file=f)

        # Output node list.
        for n in self.nodes:
            print('  ' + n.name, end=' ', file=f)
            self.writeprops(f, n)
            print(';', file=f)
        print('', file=f)

        # Output edge list.
        for e in self.edges:
            print('  ' + e.nfrom, '->', e.nto, end=' ', file=f)
            self.writeprops(f, e)
            print(';', file=f)

        print('}', file=f)


# block obj -> node string with quotations
def getBlockNodeName(b):
    return blockNumToNodeName(b['number'])

# int -> node string with quotations
def blockNumToNodeName(i):
    return quote('Block' + str(i))

# resumePoint obj -> HTML-formatted string
def getResumePointRow(rp, mode):
    if mode != None and mode != rp['mode']:
        return ''

    # Left column: caller.
    rpCaller = '<td align="left"></td>'
    if 'caller' in rp:
        rpCaller = '<td align="left">&#40;&#40;%s&#41;&#41;</td>' % str(rp['caller'])

    # Middle column: ordered contents of the MResumePoint.
    insts = ''.join('%s ' % t for t in rp['operands'])
    rpContents = '<td align="left"><font color="grey50">resumepoint %s</font></td>' % insts

    # Right column: unused.
    rpRight = '<td></td>'

    return '<tr>%s%s%s</tr>' % (rpCaller, rpContents, rpRight)

# memInputs obj -> HTML-formatted string
def getMemInputsRow(list):
    if len(list) == 0:
        return ''

    # Left column: caller.
    memLeft = '<td align="left"></td>'

    # Middle column: ordered contents of the MResumePoint.
    insts = ''.join('%s ' % str(t) for t in list)
    memContents = '<td align="left"><font color="grey50">memory %s</font></td>' % insts

    # Right column: unused.
    memRight = '<td></td>'

    return '<tr>%s%s%s</tr>' % (memLeft, memContents, memRight)

# Outputs a single row for an instruction, excluding MResumePoints.
# instruction -> HTML-formatted string
def getInstructionRow(inst):
    # Left column: instruction ID.
    instId = str(inst['id'])
    instLabel = '<td align="right" port="i%s">%s</td>' % (instId, instId)

    # Middle column: instruction name.
    instName = cgi.escape(inst['opcode'])
    if 'attributes' in inst:
        if 'RecoveredOnBailout' in inst['attributes']:
            instName = '<font color="gray50">%s</font>' % instName
        elif 'Movable' in inst['attributes']:
            instName = '<font color="blue">%s</font>' % instName
        if 'NeverHoisted' in inst['attributes']:
            instName = '<u>%s</u>' % instName
        if 'InWorklist' in inst['attributes']:
            instName = '<font color="red">%s</font>' % instName
    instName = '<td align="left">%s</td>' % instName

    # Right column: instruction MIRType.
    instType = ''
    if 'type' in inst and inst['type'] != "None":
        instType = '<td align="left">%s</td>' % cgi.escape(inst['type'])

    return '<tr>%s%s%s</tr>' % (instLabel, instName, instType)

# block obj -> HTML-formatted string
def getBlockLabel(b):
    s =  '<<table border="0" cellborder="0" cellpadding="1">'

    if 'blockUseCount' in b:
        blockUseCount = "(Count: %s)" % str(b['blockUseCount'])
    else:
        blockUseCount = ""

    blockTitle = '<font color="white">Block %s %s</font>' % (str(b['number']), blockUseCount)
    blockTitle = '<td align="center" bgcolor="black" colspan="3">%s</td>' % blockTitle
    s += '<tr>%s</tr>' % blockTitle
    s += '<tr><td align="center" colspan="3">' + ' ' * 300 + '</td></tr>'

    if 'resumePoint' in b:
        s += getResumePointRow(b['resumePoint'], None)

    for inst in b['instructions']:
        if 'resumePoint' in inst:
            s += getResumePointRow(inst['resumePoint'], 'At')

        s += getInstructionRow(inst)

        if 'memInputs' in inst:
            s += getMemInputsRow(inst['memInputs'])

        if 'resumePoint' in inst:
            s += getResumePointRow(inst['resumePoint'], 'After')

    s += '</table>>'
    return s

# str -> ir obj -> ir obj -> Graph
# 'ir' is the IR to be used.
# 'mir' is always the MIR.
#  This is because the LIR graph does not contain successor information.
def buildGraphForIR(name, func, ir, mir):
    if len(ir['blocks']) == 0:
        return None

    g = Graph(name, func, 'digraph')
    g.addprops({'rankdir':'TB', 'splines':'true'})

    for i in range(0, len(ir['blocks'])):
        bactive = ir['blocks'][i] # Used for block contents.
        b = mir['blocks'][i] # Used for drawing blocks and edges.

        node = Node(getBlockNodeName(bactive))
        node.addprops({
            'shape' : 'box',
            'fontname' : '"Consolas Bold"',
            'fontsize' : 10,
            'label' : getBlockLabel(bactive)
        })

        if 'backedge' in b['attributes']:
            node.addprops({'color':'red'})
        if 'loopheader' in b['attributes']:
            node.addprops({'color':'green'})
        if 'splitedge' in b['attributes']:
            node.addprops({'style':'dashed'})

        g.addnode(node)

        for succ in b['successors']: # which are integers
            edge = Edge(getBlockNodeName(bactive), blockNumToNodeName(succ))

            if len(b['successors']) == 2:
                if succ == b['successors'][0]:
                    edge.addprops({
                        'label':'1',
                        'color' : 'green'
                    })
                else:
                    edge.addprops({
                        'label':'0',
                        'color' : 'red'
                    })

            g.addedge(edge)

    return g

# pass obj -> output file -> (Graph OR None, Graph OR None)
# The return value is (MIR, LIR); either one may be absent.
def buildGraphsForPass(p, func):
    name = p['name']
    mir = p['mir']
    lir = p['lir']
    return (buildGraphForIR(name, func, mir, mir), buildGraphForIR(name, func, lir, mir))

# function obj -> (Graph OR None, Graph OR None) list
# First entry in each tuple corresponds to MIR; second, to LIR.
def buildGraphs(func):
    graphstup = []
    for p in func['passes']:
        gtup = buildGraphsForPass(p, func)
        graphstup.append(gtup)
    return graphstup

# function obj -> (Graph OR None, Graph OR None) list
# Only builds the final pass.
def buildOnlyFinalPass(func):
    if len(func['passes']) == 0:
        return [None, None]
    p = func['passes'][-1]
    return [buildGraphsForPass(p, func)]

# Add in closing } and ] braces to close a JSON file in case of error.
def parenthesize(s):
    stack = []
    inString = False

    for c in s:
        if c == '"': # Doesn't handle escaped strings.
            inString = not inString

        if not inString:
            if   c == '{' or c == '[':
                stack.append(c)
            elif c == '}' or c == ']':
                stack.pop()

    while stack:
        c = stack.pop()
        if   c == '{': s += '}'
        elif c == '[': s += ']'

    return s

def iongraph(args):
    passes = []
    # Write out a graph, constructing a nice filename.
    # function id -> pass id -> IR string -> Graph -> void
    def outputPass(fnum, pnum, irname, g):
        funcid = str(fnum).zfill(2)
        passid = str(pnum).zfill(2)

        filename = 'func%s-pass%s-%s-%s.gv' % (funcid, passid, g.name, str(irname))
        filepath = os.path.join(folder_out, filename)
        with open(filepath, 'w') as fd:
            g.write(fd)
        passes.append(filename)

    s = open('/tmp/ion.json', 'r').read()
    ion = json.loads(parenthesize(s))
    for i in range(0, len(ion['functions'])):
        func = ion['functions'][i]

        if args.funcnum >= 0 and i != args.funcnum:
            continue

        gtl = buildOnlyFinalPass(func) if args.final else buildGraphs(func)

        if len(gtl) == 0:
            sys.stderr.write(" function %d (%s): abort during SSA construction.\n" % (i, func['name']))
        else:
            sys.stderr.write(" function %d (%s): success; %d passes.\n" % (i, func['name'], len(gtl)))

        for j in range(0, len(gtl)):
            gt = gtl[j]
            if gt == None:
                continue

            mir = gt[0]
            lir = gt[1]

            if args.passnum >= 0 and j == args.passnum:
                if lir != None and args.out_lir:
                    lir.write(args.out_lir)
                if mir != None and args.out_mir:
                    mir.write(args.out_mir)
                if args.out_lir and args.out_mir:
                    break
            elif args.passnum >= 0:
                continue

            # If only the final pass is requested, output both MIR and LIR.
            if args.final:
                if lir != None:
                    outputPass(i, j, 'lir', lir)
                if mir != None:
                    outputPass(i, j, 'mir', mir)
                continue

            # Normally, only output one of (MIR, LIR), preferring LIR.
            if lir != None:
                outputPass(i, j, 'lir', lir)
            elif mir != None:
                outputPass(i, j, 'mir', mir)

    drop_index(passes)

def drop_index(passes):
    index = '''<!-- Axel '0vercl0k' Souchet - 10 May 2019 -->
<!DOCTYPE html>
<html>
    <meta http-equiv='Cache-Control' content='no-cache, no-store, must-revalidate' />
    <meta http-equiv='Pragma' content='no-cache' />
    <meta http-equiv='Expires' content='0' />
<head>
    <title>ghetto-iongraph</title>
    <script src="https://cdn.jsdelivr.net/npm/@viz-js/viz@3.6.0/lib/viz-standalone.min.js"></script>
    <script type='text/javascript'>
    function OnChange(e) {

        //
        // When the drop-down has changed, we generate the SVG.
        // To do so, we fetch the graphviz file and pass it to Viz.
        //

        const Pass = e.target.value;
        const Content = fetch(Pass).then(r => {
            return r.text();
        }).then(Content => {
            Viz.instance().then(function(viz) {
                var svg = viz.renderSVGElement(Content);
                document.getElementById('svg').innerHTML="";
                document.getElementById('svg').appendChild(svg);
            });
        });
    }

    function OnLoad() {

        //
        // On load we create a drop-down box with every
        // files that have been generated.
        // Don't forget to hook-up the `onchange` event to be able
        // to generate the SVG graph associated to the graphviz file.
        //

        const Options = [%s];
        const Select = document.createElement('select');
        Select.onchange = OnChange;
        for(const Option of Options) {
            const Tag = document.createElement('option');
            Tag.value = Option;
            Tag.innerText = Option;
            Select.options.add(Tag);
        }

        //
        // Add it to the DOM!
        //

        document.getElementById('select').appendChild(Select);

        //
        // Simulate an event.
        //

        OnChange({target: Select});
    }
    </script>
</head>
<body onload='OnLoad();' style='background-image:url(https://doar-e.github.io/images/themes03_light.gif)'>
<center>
<div id='select'></div>
<div id='svg'></div>
</center>
</body>
</html>
''' % (', '.join("'%s'" % p for p in passes))
    filepath = os.path.join(folder_out, 'index.html')
    with open(filepath, 'w') as f:
        f.write(index)

def main(argc, argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('--js-path', help = 'js.exe bin path.', required = True)
    parser.add_argument('--script-path', help = 'script to execute', required = True)
    parser.add_argument('--overwrite', help = 'overwrite', default = False, action = 'store_true')
    # Taken from iongraph.py
    parser.add_argument(
        '--funcnum',
        help = 'Only operate on the specified function, by index.',
        type = int,
        default = -1
    )
    parser.add_argument(
        '--passnum',
        help = 'Only operate on the specified pass, by index.'
    )
    parser.add_argument(
        '--final',
        help = 'Only generate the final optimized MIR/LIR graphs.',
        action = 'store_true'
    )
    args = parser.parse_args()
    if os.path.isdir(folder_out):
        print('The directory iongraph-out is already present, aborting.')
        if not args.overwrite:
            return

        print('Overwrite is enabled so removing the folder..')
        shutil.rmtree(folder_out)

    os.mkdir(folder_out)
    # Set the ionflags.
    os.environ['IONFLAGS'] = 'logs,scripts,osi,bailouts'
    subprocess.call([
        args.js_path,
        # Strict mode.
        #'-s',
        # Avoid races in ion when spewing.
        '--ion-offthread-compile=off',
        args.script_path
    ])

    if not os.path.isfile('/tmp/ion.json'):
        print('Something does not look right, ion.json has not been created, aborting.')
        return 0

    iongraph(args)
    return 1

if __name__ == '__main__':
    sys.exit(main(len(sys.argv), sys.argv))

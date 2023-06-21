import os
import re
import subprocess as sp
import sys
import pathogenprofiler as pp
from uuid import uuid4
import json
import csv
import statistics as stats
from collections import defaultdict
from glob import glob
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


__version__ = "0.0.7"


def plot_lofreq_results(prefix):
    # Read lofreq results
    df = pd.read_csv(f"{prefix}.lofreq.tsv",delimiter="\t",header = None)
    df.rename(columns={0: 'position', 1:'ref',2:'alt',3:'frequency',4:'depth',5:'qual'}, inplace=True)
    
    # Read depth
    dp = pd.read_csv(f"{prefix}.consensus.depth.txt", delimiter="\t",header = None)
    dp.rename(columns={0: 'chrom', 1:'pos',2:'depth'}, inplace=True)

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Add traces colouring by depth setting the max and min of the colour scale
    fig.add_trace(
        go.Scatter(
            x=df.position, 
            y=df.frequency, 
            name="Lofreq SNP",
            mode='markers', 
            marker=dict(color=df.qual, colorscale='Viridis',showscale=True,cmin=65,cmax=200),
        ),
        secondary_y=False, 
    )

    # Add depth trace
    fig.add_trace(
        go.Scatter(x=dp.pos, y=dp.depth, name="Depth",mode='lines'),
        secondary_y=True
    )

    # add legend on top left
    fig.update_layout(
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        )

    )

    # use simple white template
    fig.update_layout(template='simple_white')

    # write to pdf
    fig.write_image(f"{prefix}.lofreq.pdf")


def remove_bwa_index(ref):
    for e in ["amb","ann","bwt","pac","sa"]:
        os.remove(f"{ref}.{e}")

def pilon_correct(ref,r1,r2,prefix,threads=1):
    tmp = str(uuid4())
    run_cmd(f"cp {ref} {tmp}.ref.fasta")
    run_cmd(f"bwa index {tmp}.ref.fasta")
    
    run_cmd(f"bwa mem -t {threads} -R '@RG\\tID:{prefix}\\tSM:{prefix}\\tPL:Illumina' {tmp}.ref.fasta {r1} {r2} | samtools sort -@ {threads} -o {tmp}.bam")
    run_cmd(f"samtools index {tmp}.bam")
    run_cmd(f"pilon -Xmx10g --genome {tmp}.ref.fasta --frags {tmp}.bam --output {prefix}")
    run_cmd(f"sed -i 's/_pilon//' {prefix}.fasta")
    for f in glob(f"{tmp}.*"):
        os.remove(f)
    



class Report:
    def __init__(self,report_file):
        self.report = {}
        self.report_file = report_file
    def set(self,key,value):
        self.report[key] = value
        self.dump()
    def set_dict(self,d):
        for key,value in d.items():
            self.set(key,value)
        self.dump()
    def dump(self):
        with open(self.report_file,"w") as O:
            json.dump(self.report,O,indent=4)


def get_fastq_stats(fastq_files):
    tmpfile = "%s.txt" % uuid4()
    run_cmd(f"seqkit stats -T {' '.join(fastq_files)} > {tmpfile}")
    numreads = 0
    lengths = []
    for row in csv.DictReader(open(tmpfile),delimiter="\t"):
        numreads  += int(row['num_seqs'])
        lengths.append(float(row['avg_len']))
    
    os.remove(tmpfile)

    return {
        "Number of reads":numreads,
        "Average read length": stats.mean(lengths),
    }

def kreport_extract_human(kreport_file):
    """
    Extract the human reads from a kraken report file.
    """
    human_reads = 0
    for line in open(kreport_file):
        if line.strip().split("\t")[4] == "9606":
            human_reads = float(line.strip().split("\t")[0])
    return {"Read percent human":human_reads}

def kreport_extract_dengue(kreport_file):
    """
    Extract the Dengue reads from a kraken report file.
    """
    dengue_reads = 0
    d1_reads = 0
    d2_reads = 0
    d3_reads = 0
    d4_reads = 0
    for line in open(kreport_file):
        if line.strip().split("\t")[4] == "12637":
            dengue_reads = float(line.strip().split("\t")[0])
        if line.strip().split("\t")[4] == "11053":
            d1_reads = float(line.strip().split("\t")[0])
        if line.strip().split("\t")[4] == "11060":
            d2_reads = float(line.strip().split("\t")[0])
        if line.strip().split("\t")[4] == "11069":
            d3_reads = float(line.strip().split("\t")[0])
        if line.strip().split("\t")[4] == "11070":
            d4_reads = float(line.strip().split("\t")[0])
    return {
        "Read percent dengue":dengue_reads, 
        "Read percent dengue 1":d1_reads, 
        "Read percent dengue 2":d2_reads, 
        "Read percent dengue 3":d3_reads, 
        "Read percent dengue 4":d4_reads
    }

def run_cmd(cmd):
    sys.stderr.write(f"Running: {cmd}\n")
    sp.call(cmd,shell=True)

class Sample:
    def __init__(self,prefix,r1,r2):
        self.prefix = prefix
        self.r1 = r1
        self.r2 = r2

    def __repr__(self):
        return f"Sample(prefix={self.prefix},r1={self.r1},r2={self.r2})"


def sort_out_paried_files(files,r1_suffix="_S[0-9]+_L001_R1_001.fastq.gz",r2_suffix="_S[0-9]+_L001_R2_001.fastq.gz"):
    prefixes = defaultdict(lambda:{"r1":[],"r2":[]})

    for f in files:
        tmp1 = re.search("(.+)%s" % r1_suffix,f)
        tmp2 = re.search("(.+)%s" % r2_suffix,f)
        p = None
        if tmp1:
            p = tmp1.group(1).split("/")[-1]
            prefixes[p]['r1'].append(f)
        elif tmp2:
            p = tmp2.group(1).split("/")[-1]
            prefixes[p]['r2'].append(f)
            
    runs = []
    for p,vals in prefixes.items():
        if len(vals['r1'])!=1:
            raise Exception("%s has number of R1 files != 1 %s. Please check." % (p,vals['r1']))
        if len(vals['r2'])!=1:
            raise Exception("%s has number of R2 files != 1 %s. Please check." % (p,vals['r2']))
        runs.append(
            Sample(p,vals['r1'][0],vals['r2'][0]))
    return runs

def find_fastq_files(directory):
    """
    Find fastq files in a directory and return a 
    list of tuples with the sample name and the 
    path to the fastq files from both pairs.
    """
    files = [f"{os.path.abspath(directory)}/{f}" for f in os.listdir(directory)]
    fastq_files = sort_out_paried_files(files)
    
    return fastq_files


def get_fasta_missing_content(fasta_file):
    """
    Get the missing content of a fasta file.
    """
    fasta = pp.fasta(fasta_file)
    seq = list(fasta.fa_dict.values())[0]
    missing = round(seq.count("N")/len(seq)*100)
    return missing

def mask_fasta(input,output,positions,newchrom=None):
    """
    Mask the fasta file with Ns.
    """
    fasta = pp.fasta(input)
    seq = list(list(fasta.fa_dict.values())[0])

    for chrom,pos in positions:
        seq[pos-1] = "N"
    
    with open(output,"w") as O:
        O.write(">%s\n%s\n" % (newchrom,''.join(seq)))

def get_missing_positions(bam,depth_cutoff=50):
    tmpfile = "%s.bed" % uuid4()
    run_cmd(f"bedtools genomecov -ibam {bam} -d > {tmpfile}")
    positions = []
    for line in open(tmpfile):
        chrom,pos,depth = line.strip().split("\t")
        if int(depth) < depth_cutoff:
            positions.append((chrom,int(pos)))
    os.remove(tmpfile)
    return positions

def fasta_depth_mask(input,output,bam_file,depth_cutoff=50,newchrom=None):
    """
    Mask the fasta file with Ns based on the depth of the bam file.
    """
    positions = get_missing_positions(bam_file,depth_cutoff=depth_cutoff)
    mask_fasta(input,output,positions,newchrom=newchrom)


def return_seqs_by_size(fasta_file,seq_size_cutoff):
    """
    Return a list of sequences from a fasta file that are 
    above a certain size cutoff.
    """
    fasta = pp.fasta(fasta_file)
    seqs = {}
    for name,seq in fasta.fa_dict.items():
        if len(seq) > seq_size_cutoff:
            seqs[name] = seq
    return seqs

def filter_seqs_by_size(fasta_file,output, seqname, seq_size_cutoff):
    """
    Filter a fasta file by a size cutoff.
    """
    seqs = return_seqs_by_size(fasta_file,seq_size_cutoff=seq_size_cutoff)
    if len(seqs) == 1:    
        with open(output,"w") as O:
            for name,seq in seqs.items():
                O.write(">%s\n%s\n" % (seqname,seq))
        return True
    else:
        return False

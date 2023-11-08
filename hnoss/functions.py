import os, pandas as pd, subprocess, numpy as np
import hnoss.configSettings as cfg
from pathlib import Path
from datetime import datetime, date
from json import loads, dumps
from ast import literal_eval
import matplotlib.pyplot as plt
import statsmodels.api as sm
from scipy.stats import pearsonr
from pango_aliasor.aliasor import Aliasor

#region: Freyja
def runFrejya(BAMfile: list[str], outDir: str, ref: str, refname: str = None) -> str:
    """Runs a Freyja analysis on mixed COVID samples. See https://github.com/andersen-lab/Freyja
    :param BAMfile: The BAM files to de-mix    
    :param outDir: The output directory
    :param ref: The genome FASTA reference
    """    
    if isinstance(BAMfile, list):
        freyjaOut = [runFrejya(file, outDir, ref, refname) for file in BAMfile]
    else:
        getOutFile = lambda ext: os.path.join(outDir, os.path.splitext(os.path.basename(BAMfile))[0] + ext)
        variantsOut = getOutFile(".variants.tsv")
        depthsOut = getOutFile(".depths.tsv")
        freyjaOut = getOutFile(".freyja.tsv")

        # freyja variants [bamfile] --variants [variant outfile name] --depths [depths outfile name] --ref [reference.fa]
        cmd = ["freyja", "variants", BAMfile, "--variants", variantsOut, "--depths", depthsOut, "--ref", ref]
        #if (refname is not None): cmd = cmd + ["--refname", refname]
        subprocess.run(cmd)

        # Not sure why necessary. Cannot use --refname in above command, or index file is not found, and cannot have zero count reads, or below command has a log error
        depths = pd.read_csv(depthsOut, names = ["ref","pos","nt","count"], sep="\t")
        depths = depths[depths.ref.isin([refname])]
        depths.to_csv(depthsOut, header=None, index=None, sep="\t")

        # freyja demix [variants-file] [depth-file] --output [output-file]
        subprocess.run(["freyja","demix",variantsOut,depthsOut,"--output",freyjaOut])

    return freyjaOut

def aggregateFreyja(freyja, freyjaOut):    
    #freyja aggregate [directory-of-output-files] --output [aggregated-filename.tsv] --ext output
    subprocess.run(["freyja","aggregate",freyja,"--output", freyjaOut,"--ext","freyja.tsv"])
    return freyjaOut

def plotFreyja(freyja, output):
    #freyja plot [aggregated-filename-tsv] --output [plot-filename(.pdf,.png,etc.)]
    subprocess.run(["freyja","plot",freyja,"--output", "summ-" + output])
    subprocess.run(["freyja","plot",freyja,"--lineages","--output", "lineage-" + output])        

def startFreyjaDashboard(freyja, metadata, output):
    #freyja dash [aggregated-filename-tsv] [sample-metadata.csv] [dashboard-title.txt] [introContent.txt] --output [outputname.html]
    subprocess.run(["freyja","dash",freyja,metadata,"--output",output])

def convertToAggregatedFormat(file):
    """Converts single demix file to the aggregated format
    :param file: The path to the file
    :return: A demix file in aggregated format
    """    
    freyja = importToDataFrame(file, index_col = 0)
    if len(freyja.columns) == 1: freyja = freyja.set_axis([Path(file).stem], axis=1).transpose()
    return freyja

def generateHnoss(files:list[str]) -> pd.DataFrame:
    """Aggregated Freyja lineage files into a single dataframe. Will concatenate both files created with `$freyja demix` or `$freyja aggregate`.
    :param files: The files to concatenate
    :return: A dataframe with the same format as `$freyja aggregate`
    """  
    freyjaRaw = formatFreyjaLineage(files).add_suffix("_RawLineages")
    freyjaSumm = formatFreyjaLineage(files, summarized=True).add_suffix("_SummarizedLineages")

    freyja = freyjaSumm.join(freyjaRaw).reset_index()
    dataCols = list(set(freyja.columns) - set(freyjaRaw.columns.to_list()) - set(freyjaSumm.columns.to_list()))
    freyja = freyja.rename(columns={c: c+'_SampleInfo' for c in freyja.columns if c in dataCols})
    reverseSplit = lambda str : '_'.join(str.split('_')[::-1])
    freyja.columns = [reverseSplit(col) for col in freyja.columns.to_list()]
    idx = freyja.columns.str.split('_', expand=True)
    freyja.columns = idx
    idx = pd.MultiIndex.from_product([idx.levels[0], idx.levels[1]])
    freyja.reindex(columns=idx, fill_value=-1)
    return freyja

def formatFreyjaLineage(files:list[str], summarized = False) -> pd.DataFrame:
    """Gets the lineage proportions from Frejya output files(s)
    :param file: The path to the Freyja output file(s)
    :return: A DataFrame with columns for lineages and abundances with file, resid, and coverage as the index
    """ 
    freyja = readFreyjaLineages(files = files)
    
    if (summarized):
        freyja[cfg.summarizedCol] = freyja[cfg.summarizedCol].apply(literal_eval)
        freyja = freyja.explode(cfg.summarizedCol).reset_index(drop=True)
        freyja[[cfg.lineageCol, cfg.abundCol]] = pd.DataFrame(freyja[cfg.summarizedCol].tolist(), index=freyja.index)
    else:
        freyja[cfg.lineageCol] = freyja[cfg.lineageCol].str.split(" ")
        freyja[cfg.abundCol] = freyja[cfg.abundCol].str.split(" ")
        freyja = freyja.explode([cfg.lineageCol,cfg.abundCol]).reset_index(drop=True)

    freyja = freyja.drop(columns=[cfg.summarizedCol])
    for col in [cfg.abundCol,cfg.residualCol,cfg.coverageCol]:
        freyja[col] = freyja[col].transform(lambda x: float(sigfig(float(x))))
    freyja = freyja.groupby([cfg.fileCol, cfg.residualCol, cfg.coverageCol, cfg.lineageCol])[cfg.abundCol].first().unstack() 

    return(freyja)

def readFreyjaLineages(files:list[str]) -> pd.DataFrame:
    """Aggregated Freyja lineage files into a single dataframe. Will concatenate both files created with `$freyja demix` or `$freyja aggregate`.
    :param files: The files to concatenate
    :return: A dataframe with the same format as `$freyja aggregate`
    """    
    files = files if type(files) is list else [files] 
    freyja = [convertToAggregatedFormat(f) for f in files]
    freyja = pd.concat(freyja)
    freyja = freyja.rename_axis('file').reset_index()

    return freyja

def filterFreyjaLineage(freyja: pd.DataFrame, cutoff: float = 0.05, removeEmpty = True):
    """Filters out low presence lineages
    :param freyja: A formatted Freyja lineage from formatFreyjaLineage() 
    :param cutoff: The cut-off value to exclude
    :return: Freyja lineages with value below cutoff replaced with NaN
    """    
    freyja = freyja.mask(freyja < cutoff, np.nan)
    if removeEmpty:
        freyja = freyja.dropna(axis = 1, how='all')
    return freyja

def collapseFreyjaLineage(freyja: pd.DataFrame, strains: list[str]):
    """ Collapses Freyja lineages. Cannot parse down past "A","B" or any recombinant strains
    :param freyja: A Freyja output dataset formatted with formatFreyjaOutput()
    :param strains: The strains to parse down until
    """    
    aliasor = Aliasor()

    while(True):
        cols = list(freyja.columns)
        cols = [col for col in cols if col not in [cfg.fileCol, cfg.residualCol, cfg.coverageCol]]    
        badcols = set([strain for strain in cols if strain not in strains])
        beforeCols = set(freyja.columns)

        for strain in badcols: 
            freyja = collapseStrain(freyja, strain, aliasor)
            
        freyja = freyja.groupby(freyja.columns, axis=1).sum()
        freyja = freyja.replace({0:np.nan})

        if (beforeCols == set(freyja.columns)): break

    return freyja

def collapseStrain(freyja: pd.DataFrame, strain: str, aliasor:Aliasor = None):
    """Collapse a single strain in a formatted Freyja dataset
    :param freyja: A Freyja output dataset formatted with formatFreyjaOutput()
    :param strain: The name of the strain to collapse. If it's a terminal parent (e.g., 'A','B', any 'X' strain), it cannot be collapsed further.
    :param aliasor: A pango_aliasor object. Will be generated if not specified (adds significant runtime if done repeatedly), defaults to None
    :return: A Freyja dataset with the collapsed strain (if possible)
    """        
    if (aliasor == None): aliasor = Aliasor()
    parent = aliasor.parent(strain)
    if (parent != ""): freyja = freyja.rename(columns={strain: parent})
    
    return freyja


def normalizeStrains(freyja1: pd.DataFrame, freyja2:pd.DataFrame) -> list[pd.DataFrame, pd.DataFrame]:
    """Matches the strain columns between two Freyja outputs
    :param freyja1: the first DataFrame
    :param freyja2: the second DataFrame
    :return: The modified dataframes
    """    
    strains = list(set(freyja1.columns.values) | set(freyja2.columns.values))
    freyja1 = freyja1.reindex(columns=strains)
    freyja2 = freyja2.reindex(columns=strains)
    return freyja1, freyja2

def normalizeSamples(freyja1: pd.DataFrame, freyja2:pd.DataFrame) -> list[pd.DataFrame, pd.DataFrame]:
    """Matches the strain columns between two Freyja outputs
    :param freyja1: the first DataFrame
    :param freyja2: the second DataFrame
    :return: The modified dataframes
    """    
    freyja1 = freyja1.droplevel([cfg.residualCol, cfg.coverageCol])
    freyja2 = freyja2.droplevel([cfg.residualCol, cfg.coverageCol])
    indexes = list(set(freyja1.index.values) | set(freyja2.index.values))
    freyja1 = freyja1.reindex(index=indexes)
    freyja2 = freyja2.reindex(index=indexes)
    return freyja1, freyja2

def normalizeValues(freyja: pd.DataFrame, max:int = 1) -> pd.DataFrame:
    """Normalizes values for wastewater strains
    :param freyja: A Freyja dataframe
    :param max: The upper bound of the range for normalization [0,max], defaults to 0
    :return: A normalized dataframe
    """    
    freyja = freyja.div(freyja.sum(axis=1), axis=0)
    return(freyja.applymap(sigfig)*max)

def unaliasCols(freyja: pd.DataFrame):
    aliasor = Aliasor()
    freyja.columns = [aliasor.uncompress(col) for col in freyja.columns.to_list()]
    return freyja

def codeMissingAsOther(freyja: pd.DataFrame, target:int = 1, colName:str = "Other") -> pd.DataFrame:
    """Adds a column for the missing strain proportion of each sample 
    :param freyja: A Freyja dataframe
    :param colName: The column name, defaults to "Other"
    :return: A dataframe with a column named 'colName'
    """    
    freyja[colName] = target-freyja.sum(axis=1)
    return (freyja)

def compareRuns(freyja1, freyja2, xlab, ylab, type="scatter", outFile = None, log = False):

    freyja1, freyja2 = normalizeStrains(freyja1,freyja2)
    freyja1, freyja2 = normalizeSamples(freyja1,freyja2)

    cols = list(set(freyja1.columns.to_list()) | set(freyja2.columns.to_list()))
    freyja1 = freyja1.reset_index().melt(id_vars = "file", value_vars = cols, var_name = "lineage", value_name='run1')
    freyja2 = freyja2.reset_index().melt(id_vars = "file", value_vars = cols, var_name = "lineage", value_name='run2')
    freyja = freyja1.merge(freyja2, on=['file','lineage'])

    freyja = freyja[freyja[['run1','run2']].sum(axis=1) > 0].fillna(0)
    freyja = freyja.sort_values(by=['file','lineage'])
   
    x = freyja['run1'].to_numpy().flatten()
    y = freyja['run2'].to_numpy().flatten()

    idx = np.isfinite(x) & np.isfinite(y) & np.where(np.add(x,y) != 0,True,False)

    x = x[idx]
    y = y[idx]
    sort = np.argsort(x)
    x = x[sort]
    y = y[sort]

    # print(ttest_rel(x,y))
    corr, pval = pearsonr(x, y)
    print(f'Pearsons correlation: {corr} (P-value: {pval})')

    if (type == "scatter"):   
        max = x+y
        plt.plot([0,25,50],[0,25,50])     
        if (log):            
            plt.scatter(x, y, s=5, alpha=0.5)
            z = np.polyfit(x, np.log10(y), 1)
            p = np.poly1d(z)
            plt.xscale("log")
            plt.yscale("log")
            plt.plot(x, 10**p(x), "r--")
        else:
            plt.scatter(x, y, s=5, alpha=0.5)
            a, b = np.polyfit(x, y, 1)
            plt.plot(x, a*x+b)

        plt.xlabel(xlab)
        plt.ylabel(ylab)

    elif (type == "tukey"):
        f, ax = plt.subplots(1, figsize = (8,5))
        sm.graphics.mean_diff_plot(x, y, ax = ax)

    if outFile is None:
        plt.show()
    else:
        plt.savefig(outFile)

    return freyja
#endregion

#region: Variants

def readFreyjaVariants(files: list[str]):
    variants = pd.concat([importToDataFrame(fp, sep="\t", index_col = None).assign(file=os.path.basename(fp)) for fp in files])
    names = variants.pop('file')
    variants.insert(0, 'file', names)
    return (variants)

def findMutations(variants: pd.DataFrame, mutations: pd.DataFrame) -> pd.DataFrame:
    """Finds mutations in a Freyja variants file
    :param variants: Variants data from readFreyjaVariants()
    :param mutations: A dataframe of target mutations. Must have columns 'POS', 'REF', 'ALT'.
    :return: A subset of the variants dataframe containing only the specified mutations
    """    
    cols = ['POS', 'REF', 'ALT']       
    if not pd.Series(cols).isin(variants.columns).all(): raise TypeError(f"Cols '{', '.join(cols)}' not all present in variants input file")
    if not pd.Series(cols).isin(mutations.columns).all(): raise TypeError(f"Cols '{', '.join(cols)}' not all present in mutations input file")

    found = mutations.merge(variants, on=['POS', 'REF', 'ALT'])
    found = found[variants.columns]
    return (found)

#endregion

#region: internal functions
def addIDs(freyja: pd.DataFrame, IDs: str) -> pd.DataFrame:
    IDs = pd.read_csv(IDs, sep="\t", index_col = None)
    





    IDs['Key'].assign(subkey = lambda key: x.temp_c * 9 / 5 + 32)








#endregion

#region: plotting
def plotFreyja(freyja: pd.DataFrame) -> pd.DataFrame:
    freyja = collapseSamples(freyja, date = True, location = True)

def generateAuspiceFreqs(freyja:pd.DataFrame, outFile: str):
    """Generates tip_frequences.json for Auspice. Each entry will have frequency proportion only for the day the reading was taken
    :param freyja: a formatted Freyja DataFrame
    :param outFile: The output JSON
    """    
    freyja[cfg.weekCol] = freyja[cfg.collectDateCol].transform(lambda x: fn.dateToFractionalWeek(x))

    # Generate frequencies JSON
    freqs = sorted(list(set(freyja[cfg.weekCol].values)))
    freqs = pd.DataFrame(index = freyja.index.values.tolist(),columns = freqs)
    for index, row in freyja.iterrows(): freqs.at[index, row[cfg.weekCol]] = 1
    freqs.update(freqs.div(freqs.sum(axis=0),axis=1).fillna(0))
    freqs[cfg.freqCol] = freqs.values.tolist()
    pivots = list(freqs.columns)
    pivots.remove(cfg.freqCol)
    freqs = freqs[[cfg.freqCol]]
    json = loads(freqs.to_json(orient="index"))
    json.update(  {"generated_by": {
        "program": "custom",
        "version": "0.0.1"
    }})
    json.update({"pivots": pivots})
    json = dumps(json, indent=4)

    with open(outFile, "w") as out:
        out.write(json)

    # # Generate fake tree JSON
    # freyja["div"] = 0.01
    # freyja["num_date"] = freyja[cfg.weekCol].transform(lambda x: {"value": x,"confidence":[x,x]})
    # tree = {}

    # for index,row in freyja.iterrows():
    #     row = row.to_dict()
    #     print(row)
    #     exit()

#endregion

#region: accFuncs
def sigfig(val, n:int = 3):
    """Forces value to specific number of decimal points
    :param val: The value to format
    :param n: The number of decimal places
    :return: The truncated float
    """    
    # if (n == 0): return round(val)
    return float('{0:.{1}f}'.format(float(val),n))

def dateToFractionalWeek(isoDate):
    """Converts a date to a week number
    :param dat: The date to convert, in ISO format (YYYY-MM-DD)
    :param frac: Should this return the fractional value? (e.g., year 2023, week 23 = 2023.[23/52] = 2023.442), defaults to False
    """    
    isoDate = date.fromisoformat(isoDate)
    year = isoDate.strftime("%Y")
    week = str(sigfig(int(isoDate.strftime("%V"))/52,3)[1:])
    isoDate = str(year+week)
    return(isoDate)

def importToDataFrame(filename, **kargs):
    """Generic importer to Pandas dataframes. Supports .csv, .tsv., .xlsx
    :param filename: The path to the file to import
    :param **kargs: Additional arguments to the Pandas read function
    :return: _description_
    """    
    fileExt = Path(filename).suffix
    df = pd.DataFrame()
    match fileExt:
        case ".tsv":
            df = pd.read_csv(filename, sep="\t", **kargs)
        case ".csv":
            df = pd.read_csv(filename, **kargs)
        case ".xlsx":
            df = pd.read_excel(filename, **kargs)
        case _:
            df = filename
    
    return df

def test():
    print ("blah")

#endregion


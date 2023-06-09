import pandas as pd, os, re, time

def generateMLookupDB(dir: str, outDir: str, excludeDirs: list[str] = None):
    """ Generates a mlocate.db database for indexed searching
    :param dir: The directory to search
    :param outDir: the file to save database to
    :param excludeDirs: Directories to omit
    """       
    updatedb = "updatedb --database-root '" + dir + "' --output '" + outDir + "'"
    if excludeDirs != None: updatedb = updatedb + ' --prunepaths "' + " ".join(excludeDirs) + '"'
    os.system(updatedb)

def mlocateFile(file, mLocateDB):
    import subprocess
    command = "locate --database '" + mLocateDB + "' --nofollow '" + file + "'"
    try:
        return(subprocess.check_output(command, shell=True, text=True))
    except subprocess.CalledProcessError:
        return(None)   

printFound = lambda nFiles, nFound, speed, end="\r": print("   Parsed {} files and found {} files ({}s)                 ".format(nFiles,nFound,speed),end=end)
def generateFlatFileDB(dir: str, regex: str = None, fileExt: str = None, outFile: str = None, maxFiles:int = 100000000, excludeDirs: list[str] = [], verbose: bool = True):
    """Finds all files that fit a regex in a specified folder
    :param dir: Directory to search
    :param regex: The regex to search by
    :param outFile: The output file path
    :param maxFilesRead: The maximum number of files to read, defaults to 1000
    :param excludeDirs: List of folders to exclude
    :param verbose: Print progress messages?, defaults to True
    """
    nFound = nFiles = speed = 0
    out = []
    lastCheck = startTime = time.time()
    excludeDirs = "|".join(excludeDirs)

    if not os.path.exists(dir):
        raise Exception("Directory '" + dir + "' does not exist. Cannot generate database.")

    if outFile is not None:
        out = open(outFile,'w')

    if (verbose): print("Populating database...")

    for root, dirs, files in os.walk(dir, topdown=True):
        dirs.sort(reverse=True)
        if nFound >= maxFiles: break
        for file in files:
            nFiles += 1
            match = file.endswith((fileExt)) if (regex is None) else re.match(regex, file)
            if match:
                #if re.search(excludeDirs, root) != None: continue
                path = str(root) + "/" + str(file)
                if outFile is not None: 
                    out.write(path + "\n")
                else: 
                    out.append(path)
                nFound += 1
            if (nFiles % 1000 == 0): 
                speed = str(round(1000/(time.time() - lastCheck)))
                lastCheck = time.time()
            if (verbose): printFound(nFiles,nFound,speed)

    if (verbose): printFound(nFiles,nFound,str(round(time.time() - startTime,2)),"\n")
    return (out if outFile is None else outFile)

def searchFlatFileDB(file: str, outFile: str = None, searchTerms: list[str] = [], includeTerms: list[str] = [], excludeTerms: list[str] = [], caseSensitive = False, verbose = True):
    """Searches a flat file database. 
    :param inFile: The original database path
    :param outFile: The path to save the subset database in, will output list otherwise
    :param searchTerms: Strings that paths must include
    :param includeTerms: Strings that paths must include at least one of 
    :param excludeTerms: Strings that paths must not include
    """
    if isinstance(searchTerms, str): searchTerms = [searchTerms]
    if isinstance(includeTerms, str): includeTerms = [includeTerms]
    if isinstance(excludeTerms, str): excludeTerms = [excludeTerms]

    if (not caseSensitive):
        searchTerms = [term.lower() for term in searchTerms]
        includeTerms = [term.lower() for term in includeTerms]
        excludeTerms = [term.lower() for term in excludeTerms]

    if not os.path.exists(file):
        raise Exception("File '" + file + "' does not exist. Cannot generate database.")

    if outFile is not None:
        out = open(outFile,'w')
    else:
        out =[]

    if (verbose): print("Searching for files...")
    nFound = nFiles = speed = 0
    lastCheck = startTime = time.time()

    with open(file) as inDB:
        for line in inDB:
            nFiles += 1
            lineCheck = line if (caseSensitive) else line.lower()
            fnd = all(term in lineCheck for term in searchTerms) if len(searchTerms) else True
            inc = any(term in lineCheck for term in includeTerms) if len(includeTerms) else True
            exc = not any(term in lineCheck for term in excludeTerms) if len(excludeTerms) else True
            if (fnd and inc and exc): 
                if outFile is not None: 
                    out.write(line)
                else: 
                    out.append(line.strip())
                nFound += 1
            if (nFiles % 1000 == 0): 
                speed = str(round(1000/(time.time() - lastCheck)))
                lastCheck = time.time()
            if (verbose): printFound(nFiles,nFound,speed)
    
    if (verbose): printFound(nFiles,nFound,str(round(time.time() - startTime,2)),"\n")
    return (out if outFile is None else outFile)

def expandZipFlatFileDB(file: str):
    import zipfile, tempfile, shutil

    tempFile = tempfile.TemporaryFile()

    with open(file) as infile:
        with open(tempFile,"w") as tempFile:
            nLines = len(infile)
            for line in infile:
                zip = zipfile.ZipFile(str.strip(line))
                names = zip.namelist()
                tempFile.write(line)
                [tempFile.write(str.strip(line) + "/" + name + "\n") for name in names]

            tempFile.close()
            os.remove(infile)
            shutil.move(tempFile, infile)

def generateDirTree(dir: list[str], outFile:str = None, startIndex:int = 1):
    """ Generates an indexed representation of a directory tree
    :param path: The folder to create the directory for
    :param outFile: The output CSV file
    :param startIndex: The start index number
    :return: Dataframe of trees
    """
    fileIndexCol = "fileIndex"
    fileNameCol = "fileName"
    pathCol = "path"
    fileTypeCol = "type"
    if isinstance(dir, str): dir = [dir] # Coerce str to list   

    # Create tree with a pre-fixed index
    def pathToDict(path, idx):
        file_token = ''
        for root, dirs, files in os.walk(path):
            files = sorted(files,  key=lambda s: re.sub('[-+]?[0-9]+', '', s)) # Sort but ignore numbers
            tree = {(str(idx) + "." + str(idx1+1) + "|" + d): pathToDict(os.path.join(root, d),str(idx) + "." + str(idx1+1)) for idx1, d in enumerate(dirs)}
            tree.update({(str(idx) + "." + str(idx2+1+len(dirs)) + "|" + f): file_token for idx2, f in enumerate(files)})
            return tree

    # Flatten the keys
    def getKeys(dl, keys=None):
        keys = keys or []
        if isinstance(dl, dict):
            keys += dl.keys()
            _ = [getKeys(x, keys) for x in dl.values()]
        elif isinstance(dl, list):
            _ = [getKeys(x, keys) for x in dl]
        return list(set(keys))

    #
    def keysToPaths(keys, path, idx):

        keys = [str(idx) + "|" + os.path.basename(path)] + keys
        paths = pd.DataFrame(keys, columns=[pathCol])
        paths[[fileIndexCol, fileNameCol]] = paths[pathCol].apply(lambda x: pd.Series(str(x).split("|")))
        sort = sorted(paths[fileIndexCol], key=lambda x: [int(y) for y in x.split('.')])
        paths = paths.set_index(fileIndexCol).reindex(sort).reset_index().drop(columns=[pathCol])
        paths[[pathCol]] = path
        return (paths)

    def addDirectoryNames(paths):
        for index, row in paths.iterrows():
            if (index == 0): continue
            parentIdx = os.path.splitext(row[fileIndexCol])[0]
            parentRow = paths.loc[paths[fileIndexCol] == parentIdx]
            paths.at[index,pathCol] = parentRow.iloc[0][pathCol] + "/" + row[fileNameCol]
        return (paths)

    def addFileTypes(paths):
        paths[fileTypeCol] = paths[fileNameCol].apply(lambda name: "Folder" if (os.path.splitext(name)[1] == "") else os.path.splitext(name)[1][1:])
        return(paths)

    # Parse to dataframe
    def pathToDF(path, idx):
        dic = pathToDict(path, idx)
        keys = getKeys(dic)
        paths = keysToPaths(keys,path,idx)
        paths = addDirectoryNames(paths)
        paths = addFileTypes(paths)        
        return paths

    trees = pd.DataFrame()
    for idx,path in enumerate(dir):
        print(path)
        tree = pathToDF(path, idx+startIndex)
        if outFile is None:
            trees = pd.concat([trees,tree], ignore_index=True)
        else:
            tree.to_csv(outFile, mode='w' if (idx ==0) else 'a', header=not os.path.exists(outFile))

    return (trees if outFile is None else outFile)

def listSubDir(dir: list[str], absolutePath: bool = True, onlyDirs: bool = True, minFolders: int = 2, traverseOrphanDirs: bool = False):
    """Lists all subdirectories in a path. If given a list, all subdirectories for all paths.
    :param path: The parent folder(s)
    :param absolutePath: Return the absolute path?, defaults to True
    :param onlyDirs: Return only directorys, excludes files, defaults to True
    :param minFolders: Continue traversing if few folders exist?, defaults to 2
    :param traverseOrphanDirs: If a folder only contains a single folder, should I traverse through that folder?, defaults to False
    :return: All paths to the subfolders
    """    
    def traverseOrphanFolder(path:str):
        subpaths = list(os.scandir(path))
        if (len(subpaths) == 1):
            if (subpaths[0].is_dir()):
                return traverseOrphanFolder(subpaths[0].path)
        return path

    subpaths = ""
    if (type(dir) == str):
        if onlyDirs: 
            subpaths = [f.path for f in os.scandir(dir) if f.is_dir()]
            #print(subpaths)
            if (traverseOrphanDirs): subpaths = [traverseOrphanFolder(f) for f in subpaths]
            #print(subpaths)
        else: subpaths = [f.path for f in os.scandir(dir)]
        if absolutePath == False: subpaths = [os.path.basename(subpath) for subpath in subpaths]
    elif (type(dir) == list): 
        subpaths = [listSubDir(p, absolutePath, minFolders) for p in dir]
        subpaths = sum(subpaths,[])
        subpaths = [subpath + "/" for subpath in subpaths]
    else:
        return []
    return subpaths

def str_search(pattern:str, input:list[str], trim:bool = True):
    """Searches a string to see if a specific pattern is present
    :param pattern: Regular expression to search with
    :param input: The string to search
    :param trim: Remove the None values, defaults to True
    :return: The strings that matched the pattern
    """    
    matches = None
    if (type(input) == str):
        matches = re.search(pattern, input)
        matches = None if matches == None else matches.string
    elif (type(input) == list):
        matches = [str_search(pattern, s) for s in input]
        if (trim): matches = [m for m in matches if m != None]
    else:
        return None
    return matches
             
def str_extract(pattern, input, trim = True):
    """Extracts a specific pattern from a string
    :param pattern: Regular expression to search with
    :param input: The string to search
    :param trim: Remove the None values, defaults to True
    :return: The strings that matched the pattern
    """    
    matches = None
    if (type(input) == str):
        matches = re.search(pattern, input)
        matches = None if matches == None else matches.group(0)
    elif (type(input) == list):
        matches = [str_extract(pattern, s) for s in input]
        if (trim): matches = [m for m in matches if m != None]
    else:
        return None
    return matches
             
def parseExtensions(dir: str, maxFiles = 100000): 
    """Gets all extensions from a target directory
    :param targetDir: The path to the target directory
    :param maxFiles: If no new extensions are found after parsing `maxFiles` files, return
    :return: A list of the found extensions
    """    
    exts = set()
    n = 0
    for root, dirs, files in os.walk(dir):
        for filename in files:
            n += 1
            ext = os.path.splitext(filename)[1]
            if ext not in exts: 
                print("Added",ext)
                exts.add(ext)
                n = 0
        if (n > maxFiles): break    
    return(exts)

def suctionBash(dir:list[str], excludeDirs: list[str]):
    # Not working, some error with (  in the script "¯\_(ツ)_/¯ "
    import textwrap
    if isinstance(excludeDirs, str): excludeDirs = [excludeDirs]
    excludeDirs = ",".join(excludeDirs)
    script = textwrap.dedent("""
        #!/bin/bash
        SEARCHDIR=%s
        EXCLUDEDIRS=%s
        IFS=$'\\n' read -r -d '' -a EXCLUDEDIRS < <(awk -F',' '{ for( i=1; i<=NF; i++ ) print $i }' <<<"$EXCLUDEDIRS")
        EXCLUDEARG=""

        for DIR in "${EXCLUDEDIRS[@]}"; do
            EXCLUDEARG+=' -not \( -path '"'*$DIR*' -prune \)"
        done

        EXCLUDEARG="${EXCLUDEARG:1}"

        FINDFILES="find $SEARCHDIR -type f $EXCLUDEARG  -exec mv --backup=numbered {} $SEARCHDIR  2> /dev/null \;"
        DELDIRS="find $SEARCHDIR/* -type d -exec rm -rf {} 2> /dev/null \;"

        eval $FINDFILES
        eval $DELDIRS
        """ % (dir, excludeDirs))

    os.system("bash -c '%s'" % script)

def suction(dir:list[str], excludeDirs: list[str]):
    """Moves all files within the specified directory to the root dir, then deletes all the folders
    :param dir: The directory to suction
    :param excludeDirs: A list of directories to ignore
    """    
    import shutil

    for root, dirs, files in os.walk(dir, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if d not in excludeDirs]
        if (root == dir): continue
        for file in files:
            shutil.move(os.path.join(root, file), dir)

    [shutil.rmtree(os.path.join(dir,d)) for d in next(os.walk(dir))[1]]
#!/usr/bin/env python3
"""Dependency-free Xcode project generation; standard library only."""
from pathlib import Path
import hashlib, json
root=Path(__file__).resolve().parent
objects={}
def key(name): return hashlib.sha1(name.encode()).hexdigest()[:24].upper()
def q(value): return json.dumps(str(value),ensure_ascii=False)
def add(name,body):
    ident=key(name); objects[ident]=body; return ident
sources=[]; resources=[]; refs=[]
for path in sorted((root/'TennisApp').rglob('*')):
    if path.suffix=='.swift' or path.name=='ModelManifest.json' or path.suffix=='.mlpackage' or path.suffix=='.lproj':
        rel=path.relative_to(root)
        typ={'.swift':'sourcecode.swift','.json':'text.json','.mlpackage':'folder.mlpackage','.lproj':'folder'}[path.suffix]
        ref=add(str(rel),f'isa = PBXFileReference; lastKnownFileType = {typ}; path = {q(rel)}; sourceTree = SOURCE_ROOT;')
        build=add('build:'+str(rel),f'isa = PBXBuildFile; fileRef = {ref};')
        refs.append(ref)
        (sources if path.suffix in ('.swift','.mlpackage') else resources).append(build)
def ids(values): return '('+','.join(values)+',)'
product=add('product','isa = PBXFileReference; explicitFileType = wrapper.application; path = TennisOffline.app; sourceTree = BUILT_PRODUCTS_DIR;')
products=add('products',f'isa = PBXGroup; children = {ids([product])}; name = Products; sourceTree = "<group>";')
group=add('main',f'isa = PBXGroup; children = {ids(refs+[products])}; sourceTree = "<group>";')
package=add('package','isa = XCLocalSwiftPackageReference; relativePath = .;')
packageProduct=add('packageProduct',f'isa = XCSwiftPackageProductDependency; package = {package}; productName = TennisCore;')
framework=add('corebuild',f'isa = PBXBuildFile; productRef = {packageProduct};')
phases=[]
for name,isa,files in [('sources','PBXSourcesBuildPhase',sources),('resources','PBXResourcesBuildPhase',resources),('frameworks','PBXFrameworksBuildPhase',[framework])]:
    phases.append(add(name,f'isa = {isa}; buildActionMask = 2147483647; files = {ids(files)}; runOnlyForDeploymentPostprocessing = 0;'))
configs=[]
for mode in ['Debug','Release']:
    configs.append(add(mode,f'''isa = XCBuildConfiguration; name = {mode}; buildSettings = {{
        SDKROOT = iphoneos; IPHONEOS_DEPLOYMENT_TARGET = 26.0; SWIFT_VERSION = 5.0;
        ALWAYS_SEARCH_USER_PATHS = NO;
        PRODUCT_BUNDLE_IDENTIFIER = com.example.tennisoffline; PRODUCT_NAME = "$(TARGET_NAME)";
        TARGETED_DEVICE_FAMILY = "1,2"; GENERATE_INFOPLIST_FILE = YES;
        INFOPLIST_KEY_CFBundleDisplayName = "网球复盘"; INFOPLIST_KEY_UILaunchScreen_Generation = YES;
        INFOPLIST_KEY_LSSupportsOpeningDocumentsInPlace = YES;
        INFOPLIST_KEY_UISupportedInterfaceOrientations = "UIInterfaceOrientationPortrait UIInterfaceOrientationLandscapeLeft UIInterfaceOrientationLandscapeRight";
        CODE_SIGN_STYLE = Automatic; SWIFT_OPTIMIZATION_LEVEL = "{'-Onone' if mode=='Debug' else '-O'}";
    }};'''))
configList=add('configs',f'isa = XCConfigurationList; buildConfigurations = {ids(configs)}; defaultConfigurationIsVisible = 0; defaultConfigurationName = Release;')
target=add('target',f'isa = PBXNativeTarget; name = TennisOffline; productName = TennisOffline; productType = "com.apple.product-type.application"; productReference = {product}; buildConfigurationList = {configList}; buildPhases = {ids(phases)}; buildRules = (); dependencies = (); packageProductDependencies = {ids([packageProduct])};')
project=add('project',f'isa = PBXProject; attributes = {{ LastUpgradeCheck = 2600; }}; buildConfigurationList = {configList}; compatibilityVersion = "Xcode 14.0"; developmentRegion = "zh-Hans"; knownRegions = ("zh-Hans",en,Base); mainGroup = {group}; productRefGroup = {products}; projectDirPath = ""; projectRoot = ""; targets = {ids([target])}; packageReferences = {ids([package])};')
out=root/'TennisOffline.xcodeproj'; out.mkdir(exist_ok=True)
(out/'project.pbxproj').write_text('// !$*UTF8*$!\n{ archiveVersion = 1; classes = {}; objectVersion = 60; objects = {\n'+''.join(f'{k} = {{ {v} }};\n' for k,v in objects.items())+f'}}; rootObject = {project}; }}\n')
print(out)

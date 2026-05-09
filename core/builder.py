import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from core.logger import error, substep, success, dim
from core.layout import OutputLayout

class AngularBuilder:
    """
    Scaffold a minimal Angular project around the extracted sources
    and run: ng build --configuration production
    """

    NG_VERSION = "^17.0.0"  # override with --ng-version

    MINIMAL_PACKAGE_JSON = {
        "name": "jsmap-recon",
        "version": "1.0.0",
        "private": True,
        "scripts": {
            "ng": "ng",
            "start": "ng serve",
            "build": "ng build --configuration production",
        },
        "dependencies": {
            "@angular/animations": "^17.0.0",
            "@angular/common": "^17.0.0",
            "@angular/compiler": "^17.0.0",
            "@angular/core": "^17.0.0",
            "@angular/forms": "^17.0.0",
            "@angular/platform-browser": "^17.0.0",
            "@angular/platform-browser-dynamic": "^17.0.0",
            "@angular/router": "^17.0.0",
            "rxjs": "~7.8.0",
            "tslib": "^2.3.0",
            "zone.js": "~0.14.0",
        },
        "devDependencies": {
            "@angular-devkit/build-angular": "^17.0.0",
            "@angular/cli": "^17.0.0",
            "@angular/compiler-cli": "^17.0.0",
            "typescript": "~5.2.0",
        },
    }

    MINIMAL_TSCONFIG = {
        "compileOnSave": False,
        "compilerOptions": {
            "baseUrl": "./",
            "outDir": "./dist/out-tsc",
            "strict": False,
            "noImplicitOverride": True,
            "noPropertyAccessFromIndexSignature": True,
            "forceConsistentCasingInFileNames": True,
            "newLine": "lf",
            "noFallthroughCasesInSwitch": True,
            "sourceMap": True,
            "declaration": False,
            "downlevelIteration": True,
            "experimentalDecorators": True,
            "moduleResolution": "node",
            "importHelpers": True,
            "target": "ES2022",
            "module": "ES2022",
            "useDefineForClassFields": False,
            "lib": ["ES2022", "dom"],
        },
        "angularCompilerOptions": {
            "enableI18nLegacyMessageIdFormat": False,
            "strictInjectionParameters": True,
            "strictInputAccessModifiers": True,
            "strictTemplates": True,
        },
    }

    ANGULAR_JSON_TEMPLATE = {
        "$schema": "./node_modules/@angular/cli/lib/config/schema.json",
        "version": 1,
        "newProjectRoot": "projects",
        "projects": {
            "jsmap-recon": {
                "projectType": "application",
                "schematics": {},
                "root": "",
                "sourceRoot": "src",
                "prefix": "app",
                "architect": {
                    "build": {
                        "builder": "@angular-devkit/build-angular:application",
                        "options": {
                            "outputPath": "dist/jsmap-recon",
                            "index": "src/index.html",
                            "browser": "src/main.ts",
                            "polyfills": ["zone.js"],
                            "tsConfig": "tsconfig.json",
                            "assets": ["src/favicon.ico", "src/assets"],
                            "styles": ["src/styles.css"],
                            "scripts": [],
                        },
                        "configurations": {
                            "production": {
                                "budgets": [
                                    {
                                        "type": "initial",
                                        "maximumWarning": "500kb",
                                        "maximumError": "1mb",
                                    },
                                    {
                                        "type": "anyComponentStyle",
                                        "maximumWarning": "2kb",
                                        "maximumError": "4kb",
                                    },
                                ],
                                "outputHashing": "all",
                            },
                            "development": {
                                "optimization": False,
                                "extractLicenses": False,
                                "sourceMap": True,
                            },
                        },
                        "defaultConfiguration": "production",
                    },
                    "serve": {
                        "builder": "@angular-devkit/build-angular:dev-server",
                        "configurations": {
                            "production": {
                                "buildTarget": "jsmap-recon:build:production"
                            },
                            "development": {
                                "buildTarget": "jsmap-recon:build:development"
                            },
                        },
                        "defaultConfiguration": "development",
                    },
                },
            }
        },
    }

    MINIMAL_APP_MODULE = """\
import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { AppComponent } from './app.component';

@NgModule({
  declarations: [AppComponent],
  imports: [BrowserModule],
  bootstrap: [AppComponent],
})
export class AppModule {}
"""

    MINIMAL_APP_COMPONENT = """\
import { Component } from '@angular/core';

@Component({
  selector: 'app-root',
  template: '<h1>jsmap-suite recon build</h1>',
  styles: []
})
export class AppComponent {}
"""

    MINIMAL_MAIN_TS = """\
import { platformBrowserDynamic } from '@angular/platform-browser-dynamic';
import { AppModule } from './app/app.module';

platformBrowserDynamic()
  .bootstrapModule(AppModule)
  .catch(err => console.error(err));
"""

    MINIMAL_INDEX_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>jsmap-suite</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <app-root></app-root>
</body>
</html>
"""

    def __init__(self, layout: OutputLayout, ng_version: Optional[str] = None):
        self.layout = layout
        self.ng_version = ng_version or self.NG_VERSION
        self.project = layout.ng_project_dir
        self.build_log = layout.log_path("build")

    def _check_prerequisites(self) -> bool:
        for tool in ["node", "npm", "ng"]:
            if not shutil.which(tool):
                error(
                    f"'{tool}' not found in PATH. Install Node.js + Angular CLI first."
                )
                error("  npm install -g @angular/cli")
                return False
        return True

    def scaffold(self, extracted_sources: Optional[Path] = None) -> bool:
        """Create minimal Angular project skeleton."""
        substep("Scaffolding Angular project structure")
        proj = self.project

        # Write config files
        (proj / "package.json").write_text(
            json.dumps(self.MINIMAL_PACKAGE_JSON, indent=2), encoding="utf-8"
        )
        (proj / "tsconfig.json").write_text(
            json.dumps(self.MINIMAL_TSCONFIG, indent=2), encoding="utf-8"
        )
        (proj / "angular.json").write_text(
            json.dumps(self.ANGULAR_JSON_TEMPLATE, indent=2), encoding="utf-8"
        )

        # Create src structure
        src = proj / "src"
        app = src / "app"
        assets = src / "assets"
        for d in [src, app, assets]:
            d.mkdir(parents=True, exist_ok=True)

        (src / "main.ts").write_text(self.MINIMAL_MAIN_TS, encoding="utf-8")
        (src / "index.html").write_text(
            self.MINIMAL_INDEX_HTML, encoding="utf-8"
        )
        (src / "styles.css").write_text(
            "/* global styles */\n", encoding="utf-8"
        )
        (src / "favicon.ico").write_bytes(b"")
        (app / "app.module.ts").write_text(
            self.MINIMAL_APP_MODULE, encoding="utf-8"
        )
        (app / "app.component.ts").write_text(
            self.MINIMAL_APP_COMPONENT, encoding="utf-8"
        )

        # If we have extracted sources, symlink / copy them in
        if extracted_sources and extracted_sources.exists():
            substep("Copying extracted sources into ng_project/src/")
            dest_recon = src / "recon"
            if dest_recon.exists():
                shutil.rmtree(dest_recon)
            shutil.copytree(
                str(extracted_sources), str(dest_recon), dirs_exist_ok=False
            )
            success("Sources copied → ng_project/src/recon/")

        success("Angular project scaffolded → ng_project/")
        return True

    def npm_install(self) -> bool:
        substep("Running npm install (this may take a minute) ...")
        try:
            result = subprocess.run(
                ["npm", "install", "--legacy-peer-deps"],
                cwd=str(self.project),
                capture_output=True,
                text=True,
                timeout=300,
            )
            log_content = result.stdout + "\n" + result.stderr
            self.build_log.write_text(log_content, encoding="utf-8")

            if result.returncode != 0:
                error("npm install failed. Check logs/build.log")
                for line in result.stderr.splitlines()[-20:]:
                    dim(line)
                return False
            success("npm install complete")
            return True
        except subprocess.TimeoutExpired:
            error("npm install timed out (>5 min)")
            return False
        except Exception as e:
            error(f"npm install error: {e}")
            return False

    def build(self) -> bool:
        """Run ng build --configuration production."""
        substep("Running:  ng build --configuration production")
        try:
            result = subprocess.run(
                ["ng", "build", "--configuration", "production"],
                cwd=str(self.project),
                capture_output=True,
                text=True,
                timeout=600,
            )
            # Append to build log
            existing = (
                self.build_log.read_text(encoding="utf-8")
                if self.build_log.exists()
                else ""
            )
            self.build_log.write_text(
                existing
                + "\n\n─── ng build ───\n"
                + result.stdout
                + "\n"
                + result.stderr,
                encoding="utf-8",
            )

            if result.returncode != 0:
                error("ng build failed. Check logs/build.log")
                for line in result.stderr.splitlines()[-30:]:
                    dim(line)
                return False

            # Show output summary
            dist_contents = list((self.project / "dist").rglob("*"))
            js_files = [f for f in dist_contents if f.suffix == ".js"]
            success(
                f"Build complete!  {len(js_files)} JS bundle(s) in ng_project/dist/"
            )

            # Copy dist to layout for easy access
            dest_dist = self.layout.ng_dist_dir
            if dest_dist.exists():
                shutil.rmtree(dest_dist)
            shutil.copytree(
                str(self.project / "dist"), str(dest_dist), dirs_exist_ok=False
            )
            success(
                f"Dist output → {dest_dist.relative_to(self.layout.root)}/"
            )
            return True

        except subprocess.TimeoutExpired:
            error("ng build timed out (>10 min)")
            return False
        except Exception as e:
            error(f"ng build error: {e}")
            return False

    def run(self, extracted_sources: Optional[Path] = None) -> bool:
        """Full pipeline: prereq check → scaffold → npm install → ng build."""
        if not self._check_prerequisites():
            return False
        if not self.scaffold(extracted_sources):
            return False
        if not self.npm_install():
            return False
        return self.build()

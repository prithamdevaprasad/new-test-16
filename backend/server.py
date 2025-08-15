from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import json
import asyncio
import subprocess
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import uuid
from datetime import datetime

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Create the main app without a prefix
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# Models
class FileContent(BaseModel):
    path: str
    content: str

class CompileRequest(BaseModel):
    code: str
    board: str
    sketch_path: str

class UploadRequest(BaseModel):
    code: str
    board: str
    port: str
    sketch_path: str

class LibraryRequest(BaseModel):
    library_name: str

class CoreRequest(BaseModel):
    core_name: str

class LibrarySearchRequest(BaseModel):
    query: str = ""

# Arduino CLI wrapper functions
def run_arduino_cli(command: List[str]) -> Dict:
    """Run arduino-cli command and return result"""
    try:
        # Add arduino-cli to PATH - check multiple possible locations
        env = os.environ.copy()
        
        # Try different possible bin paths
        possible_bin_paths = [
            ROOT_DIR.parent / 'bin',                # ../bin
            ROOT_DIR.parent.parent / 'bin',        # ../../bin
            ROOT_DIR / 'bin',                      # ./bin
            Path('/app/bin')                       # Docker path
        ]
        
        # Find the first path that exists and contains arduino-cli
        bin_path = None
        for path in possible_bin_paths:
            cli_exe = 'arduino-cli.exe' if os.name == 'nt' else 'arduino-cli'
            test_path = path / cli_exe
            if test_path.exists():
                bin_path = str(path)
                logger.info(f"Found Arduino CLI at: {test_path}")
                break
        
        if not bin_path:
            # If not found in predefined locations, try the one in the current directory
            bin_path = str(ROOT_DIR.parent / 'bin')
            logger.warning(f"Arduino CLI not found in standard locations, defaulting to: {bin_path}")
        
        env['PATH'] = f"{bin_path};{env.get('PATH', '')}"
        # Set HOME to a Windows-compatible path
        env['HOME'] = str(ROOT_DIR)
        
        # Use arduino-cli.exe on Windows
        if command[0] == 'arduino-cli' and os.name == 'nt':
            command[0] = 'arduino-cli.exe'
            
        # Log the command being executed
        logger.info(f"Executing command: {' '.join(command)}")
        logger.info(f"Using bin_path: {bin_path}")
        
        # Check if the executable exists
        cli_path = Path(bin_path) / command[0]
        if not cli_path.exists():
            return {
                'success': False,
                'stdout': '',
                'stderr': f"Arduino CLI executable not found at {cli_path}",
                'returncode': -1
            }
        
        # Execute the command with full path
        command[0] = str(cli_path)
        logger.info(f"Full command path: {command[0]}")
        
        # Run with binary output to avoid encoding issues
        result = subprocess.run(
            command,
            capture_output=True,
            text=False,  # Changed to binary mode
            env=env
        )
        
        # Decode stdout and stderr with error handling
        stdout_str = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
        stderr_str = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
        
        return {
            'success': result.returncode == 0,
            'stdout': stdout_str,
            'stderr': stderr_str,
            'returncode': result.returncode
        }
    except Exception as e:
        return {
            'success': False,
            'stdout': '',
            'stderr': str(e),
            'returncode': -1
        }

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Arduino Code Editor API"}

@api_router.get("/boards")
async def get_boards():
    """Get list of available boards"""
    result = run_arduino_cli(['arduino-cli', 'board', 'listall', '--format', 'json'])
    
    if result['success']:
        try:
            boards = json.loads(result['stdout'])
            return {"success": True, "boards": boards.get('boards', [])}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse board list"}
    
    return {"success": False, "error": result['stderr']}

@api_router.get("/boards/available")
async def get_available_boards():
    """Get list of all available boards for installation"""
    result = run_arduino_cli(['arduino-cli', 'board', 'listall', '--format', 'json'])
    
    if result['success']:
        try:
            boards = json.loads(result['stdout'])
            return {"success": True, "boards": boards.get('boards', [])}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse available boards"}
    
    return {"success": False, "error": result['stderr']}

@api_router.post("/libraries/search")
async def search_libraries(request: LibrarySearchRequest):
    """Search for libraries"""
    if request.query:
        result = run_arduino_cli(['arduino-cli', 'lib', 'search', request.query, '--format', 'json'])
    else:
        result = run_arduino_cli(['arduino-cli', 'lib', 'search', '--format', 'json'])
    
    if result['success']:
        try:
            libraries = json.loads(result['stdout'])
            return {"success": True, "libraries": libraries.get('libraries', [])}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse library search results"}
    
    return {"success": False, "error": result['stderr']}

@api_router.get("/cores")
async def get_cores():
    """Get list of installed cores"""
    result = run_arduino_cli(['arduino-cli', 'core', 'list', '--format', 'json'])
    
    if result['success']:
        try:
            cores = json.loads(result['stdout'])
            return {"success": True, "cores": cores.get('platforms', [])}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse cores"}
    
    return {"success": False, "error": result['stderr']}

@api_router.get("/cores/search")
async def search_cores():
    """Get list of all available cores for installation"""
    result = run_arduino_cli(['arduino-cli', 'core', 'search', '--format', 'json'])
    
    if result['success']:
        try:
            cores = json.loads(result['stdout'])
            return {"success": True, "platforms": cores.get('platforms', [])}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse available cores"}
    
    return {"success": False, "error": result['stderr']}

@api_router.post("/cores/install")
async def install_core(request: CoreRequest):
    """Install a core"""
    result = run_arduino_cli(['arduino-cli', 'core', 'install', request.core_name])
    
    return {
        "success": result['success'],
        "message": result['stdout'] if result['success'] else result['stderr']
    }

@api_router.post("/cores/uninstall")
async def uninstall_core(request: CoreRequest):
    """Uninstall a core"""
    result = run_arduino_cli(['arduino-cli', 'core', 'uninstall', request.core_name])
    
    return {
        "success": result['success'],
        "message": result['stdout'] if result['success'] else result['stderr']
    }

@api_router.get("/ports")
async def get_ports():
    """Get list of available COM ports"""
    result = run_arduino_cli(['arduino-cli', 'board', 'list', '--format', 'json'])
    
    if result['success']:
        try:
            ports = json.loads(result['stdout'])
            return {"success": True, "ports": ports}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse port list"}
    
    return {"success": False, "error": result['stderr']}

@api_router.get("/libraries")
async def get_libraries():
    """Get list of installed libraries"""
    result = run_arduino_cli(['arduino-cli', 'lib', 'list', '--format', 'json'])
    
    if result['success']:
        try:
            libraries = json.loads(result['stdout'])
            return {"success": True, "libraries": libraries.get('installed_libraries', [])}
        except json.JSONDecodeError:
            return {"success": False, "error": "Failed to parse library list"}
    
    return {"success": False, "error": result['stderr']}

@api_router.post("/libraries/install")
async def install_library(request: LibraryRequest):
    """Install a library"""
    result = run_arduino_cli(['arduino-cli', 'lib', 'install', request.library_name])
    
    return {
        "success": result['success'],
        "message": result['stdout'] if result['success'] else result['stderr']
    }

@api_router.post("/libraries/uninstall")
async def uninstall_library(request: LibraryRequest):
    """Uninstall a library"""
    result = run_arduino_cli(['arduino-cli', 'lib', 'uninstall', request.library_name])
    
    return {
        "success": result['success'],
        "message": result['stdout'] if result['success'] else result['stderr']
    }

@api_router.post("/compile")
async def compile_code(request: CompileRequest):
    """Compile Arduino code"""
    # Create temp directory for sketch
    temp_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), f"arduino_sketch_{uuid.uuid4()}"))
    temp_dir.mkdir(exist_ok=True, parents=True)
    
    # Write sketch file
    sketch_file = temp_dir / f"{temp_dir.name}.ino"
    sketch_file.write_text(request.code)
    
    # Compile
    result = run_arduino_cli([
        'arduino-cli', 'compile',
        '--fqbn', request.board,
        str(temp_dir)
    ])
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    
    return {
        "success": result['success'],
        "message": result['stdout'] if result['success'] else result['stderr']
    }

@api_router.post("/upload")
async def upload_code(request: UploadRequest):
    """Upload Arduino code to board"""
    # Create temp directory for sketch
    temp_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), f"arduino_sketch_{uuid.uuid4()}"))
    temp_dir.mkdir(exist_ok=True, parents=True)
    
    # Write sketch file
    sketch_file = temp_dir / f"{temp_dir.name}.ino"
    sketch_file.write_text(request.code)
    
    # Upload
    result = run_arduino_cli([
        'arduino-cli', 'upload',
        '--fqbn', request.board,
        '--port', request.port,
        str(temp_dir)
    ])
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    
    return {
        "success": result['success'],
        "message": result['stdout'] if result['success'] else result['stderr']
    }

@api_router.get("/files/{file_path:path}")
async def get_file(file_path: str):
    """Get file content by path parameter"""
    try:
        # Handle paths that start with /tmp/arduino_workspace
        if file_path.startswith('/tmp/arduino_workspace/'):
            # Replace with the actual workspace directory
            workspace_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), "arduino_workspace"))
            relative_path = file_path.replace('/tmp/arduino_workspace/', '')
            file_path = workspace_dir / relative_path
        else:
            file_path = Path(file_path)
        if file_path.exists() and file_path.is_file():
            content = file_path.read_text()
            return {"success": True, "content": content}
        else:
            return {"success": False, "error": "File not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@api_router.get("/files")
async def get_file_by_query(path: str):
    """Get file content by query parameter"""
    try:
        logger.info(f"Loading file by query parameter: {path}")
        # Handle paths that start with /tmp/arduino_workspace
        if path.startswith('/tmp/arduino_workspace/'):
            # Replace with the actual workspace directory
            workspace_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), "arduino_workspace"))
            relative_path = path.replace('/tmp/arduino_workspace/', '')
            file_path = workspace_dir / relative_path
            logger.info(f"Mapped path: {file_path}")
        else:
            file_path = Path(path)
            logger.info(f"Direct path: {file_path}")
        if file_path.exists() and file_path.is_file():
            content = file_path.read_text()
            logger.info(f"File loaded successfully: {file_path}, Size: {len(content)} bytes")
            return {"success": True, "content": content}
        else:
            logger.error(f"File not found: {file_path}")
            return {"success": False, "error": "File not found"}
    except Exception as e:
        logger.error(f"Error loading file: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}

@api_router.post("/files")
async def save_file(file_data: FileContent):
    """Save file content"""
    try:
        # Log the incoming request
        logger.info(f"Saving file: {file_data.path}, Content length: {len(file_data.content)}")
        
        # Handle paths that start with /tmp/arduino_workspace
        if file_data.path.startswith('/tmp/arduino_workspace/'):
            # Replace with the actual workspace directory
            workspace_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), "arduino_workspace"))
            relative_path = file_data.path.replace('/tmp/arduino_workspace/', '')
            file_path = workspace_dir / relative_path
            logger.info(f"Mapped path: {file_path}")
        else:
            file_path = Path(file_data.path)
            logger.info(f"Direct path: {file_path}")
        
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if it's an .ino or .fzz file
        is_ino_file = file_path.suffix.lower() == '.ino'
        is_fzz_file = file_path.suffix.lower() == '.fzz'
        if is_ino_file:
            logger.info(f"Detected .ino file: {file_path}")
        elif is_fzz_file:
            logger.info(f"Detected .fzz file: {file_path}")
        
        # Write the file content
        with open(file_path, 'w', newline='') as f:
            f.write(file_data.content)
        
        # Verify the file was written
        if file_path.exists():
            file_size = file_path.stat().st_size
            logger.info(f"File saved successfully: {file_path}, Size: {file_size} bytes")
            
            # Double-check content for .ino and .fzz files
            if is_ino_file or is_fzz_file:
                with open(file_path, 'r') as f:
                    saved_content = f.read()
                if saved_content != file_data.content:
                    file_type = ".ino" if is_ino_file else ".fzz"
                    logger.error(f"Content mismatch for {file_type} file: {file_path}")
                    logger.error(f"Expected length: {len(file_data.content)}, Actual length: {len(saved_content)}")
                    # Try again with binary mode
                    with open(file_path, 'wb') as f:
                        f.write(file_data.content.encode('utf-8'))
                    logger.info(f"Retried saving {file_type} file in binary mode: {file_path}")
            
            return {"success": True, "message": f"File saved successfully. Size: {file_size} bytes"}
        else:
            logger.error(f"File not found after write: {file_path}")
            return {"success": False, "error": "File not found after write operation"}
    except Exception as e:
        logger.error(f"Error saving file: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}

@api_router.delete("/files")
async def delete_file(path: str):
    """Delete a file"""
    try:
        # Handle paths that start with /tmp/arduino_workspace
        if path.startswith('/tmp/arduino_workspace/'):
            # Replace with the actual workspace directory
            workspace_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), "arduino_workspace"))
            relative_path = path.replace('/tmp/arduino_workspace/', '')
            file_path = workspace_dir / relative_path
        else:
            file_path = Path(path)
        
        # Log file deletion attempt
        logger.info(f"Attempting to delete file: {file_path}")
        
        # Check if it's an .ino or .fzz file for logging purposes
        if file_path.suffix.lower() == '.ino':
            logger.info(f"Deleting .ino file: {file_path}")
        elif file_path.suffix.lower() == '.fzz':
            logger.info(f"Deleting .fzz file: {file_path}")
            
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
            logger.info(f"File deleted successfully: {file_path}")
            return {"success": True, "message": "File deleted successfully"}
        else:
            logger.error(f"File not found for deletion: {file_path}")
            return {"success": False, "error": "File not found"}
    except Exception as e:
        logger.error(f"Error deleting file: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "error": str(e)}

@api_router.get("/workspace")
async def get_workspace():
    """Get workspace file tree"""
    workspace_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), "arduino_workspace"))
    workspace_dir.mkdir(exist_ok=True, parents=True)
    
    def build_tree(path: Path):
        tree = []
        try:
            for item in path.iterdir():
                if item.is_file():
                    # Get file size for all files
                    file_size = item.stat().st_size
                    
                    # Create file entry with additional metadata
                    file_entry = {
                        "name": item.name,
                        "path": str(item),
                        "type": "file",
                        "size": file_size
                    }
                    
                    # Add file type information for .ino and .fzz files
                    if item.suffix.lower() == '.ino':
                        file_entry["file_type"] = "arduino"
                    elif item.suffix.lower() == '.fzz':
                        file_entry["file_type"] = "circuit"
                    
                    tree.append(file_entry)
                elif item.is_dir():
                    tree.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "directory",
                        "children": build_tree(item)
                    })
        except PermissionError:
            logger.error(f"Permission error accessing {path}")
            pass
        except Exception as e:
            logger.error(f"Error building tree for {path}: {str(e)}")
            pass
        return tree
    
    return {"success": True, "tree": build_tree(workspace_dir)}

# WebSocket for serial monitor
@app.websocket("/api/serial/{port}")
async def serial_websocket(websocket: WebSocket, port: str):
    await manager.connect(websocket)
    process = None
    try:
        # Start serial monitor
        env = os.environ.copy()
        bin_path = str(ROOT_DIR.parent / 'bin')
        env['PATH'] = f"{bin_path};{env.get('PATH', '')}"
        env['HOME'] = str(ROOT_DIR)
        
        # Use arduino-cli.exe on Windows
        cli_command = 'arduino-cli.exe' if os.name == 'nt' else 'arduino-cli'
        cli_path = Path(bin_path) / cli_command
        
        if not cli_path.exists():
            error_msg = f"Arduino CLI executable not found at {cli_path}"
            logger.error(error_msg)
            await manager.send_personal_message(f"Error: {error_msg}", websocket)
            return
        
        # Get baudrate from query parameters (default to 9600)
        query_params = dict(websocket.query_params)
        baudrate = query_params.get('baudrate', '9600')
        
        # Log connection attempt
        logger.info(f"Attempting to connect to serial port: {port} at {baudrate} baud")
        await manager.send_personal_message(f"Connecting to {port} at {baudrate} baud...", websocket)
        
        # Start the process with stdin pipe for sending data
        try:
            # Configure serial monitor with appropriate settings
            cmd = [
                str(cli_path), 'monitor', 
                '--port', port, 
                '--config', f"baudrate={baudrate}"
                # Removed timeout setting that was causing issues
            ]
            
            logger.info(f"Running command: {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                env=env
            )
        except Exception as e:
            error_msg = f"Failed to start arduino-cli monitor: {str(e)}"
            logger.error(error_msg)
            await manager.send_personal_message(f"Error: {error_msg}", websocket)
            return
        
        # Create a task to read from stdout
        async def read_stdout():
            while process and process.poll() is None:
                try:
                    line = process.stdout.readline()
                    if line:
                        await manager.send_personal_message(line.strip(), websocket)
                except Exception as e:
                    logger.error(f"Error reading from serial: {e}")
                    break
        
        # Start the stdout reading task
        read_task = asyncio.create_task(read_stdout())
        
        # Check if process started successfully
        if process.poll() is not None:
            # Process exited immediately
            error_output = process.stderr.read()
            error_msg = f"Failed to connect to port {port}: {error_output}"
            logger.error(error_msg)
            await manager.send_personal_message(f"Error: {error_msg}", websocket)
            return
            
        # Send success message
        await manager.send_personal_message(f"Connected to {port} at {baudrate} baud", websocket)
        
        # Main loop to handle incoming WebSocket messages
        while True:
            if process.poll() is not None:
                error_output = process.stderr.read()
                if error_output:
                    logger.error(f"Process error: {error_output}")
                    await manager.send_personal_message(f"Error: Port monitor error: {error_output}", websocket)
                else:
                    await manager.send_personal_message(f"Serial connection closed", websocket)
                break
                
            # Check for WebSocket messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                # Send data to serial port
                if process and process.poll() is None:
                    try:
                        process.stdin.write(data + '\n')
                        process.stdin.flush()
                        logger.info(f"Sent to serial: {data}")
                    except Exception as e:
                        logger.error(f"Error sending to serial: {e}")
                        await manager.send_personal_message(f"Error sending: {str(e)}", websocket)
                else:
                    await manager.send_personal_message(f"Error: Serial connection is closed", websocket)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for port {port}")
                break
            except Exception as e:
                logger.error(f"Unexpected error in WebSocket loop: {e}")
                await manager.send_personal_message(f"Error: {str(e)}", websocket)
                break
        
        # Cancel the read task
        if read_task and not read_task.done():
            read_task.cancel()
            
    except WebSocketDisconnect:
        logger.info(f"Serial monitor disconnected for port {port}")
    except Exception as e:
        logger.error(f"Serial monitor error: {e}")
        await manager.send_personal_message(f"Error: {str(e)}", websocket)
    finally:
        # Clean up
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception as e:
                logger.error(f"Error terminating process: {e}")
                try:
                    process.kill()
                except:
                    pass
        
        manager.disconnect(websocket)
        logger.info(f"Serial monitor connection closed for port {port}")

# Circuit Design Routes
@api_router.get("/components")
async def get_components():
    """Get all Fritzing components with accurate connector positions and SVG dimensions"""
    try:
        import os
        import xml.etree.ElementTree as ET
        from pathlib import Path
        import re
        
        components = []
        fritzing_parts_dir = ROOT_DIR / "fritzing-parts"
        
        if not fritzing_parts_dir.exists():
            return {"success": False, "error": "Fritzing parts directory not found"}
        
        # Helper function to extract category from filename or properties
        def extract_category(filename, properties_elem):
            # Try to categorize by keywords in filename
            filename_lower = filename.lower()
            if any(keyword in filename_lower for keyword in ["resistor", "resistance"]):
                return "Resistors"
            elif any(keyword in filename_lower for keyword in ["capacitor", "capacitance"]):
                return "Capacitors"
            elif any(keyword in filename_lower for keyword in ["led", "light"]):
                return "LEDs"
            elif any(keyword in filename_lower for keyword in ["transistor", "mosfet", "fet"]):
                return "Transistors"
            elif any(keyword in filename_lower for keyword in ["ic", "chip", "logic"]):
                return "ICs"
            elif any(keyword in filename_lower for keyword in ["arduino", "raspberry", "esp", "microcontroller"]):
                return "Microcontrollers"
            elif any(keyword in filename_lower for keyword in ["sensor", "detect"]):
                return "Sensors"
            elif any(keyword in filename_lower for keyword in ["button", "switch", "potentiometer", "pot"]):
                return "Input"
            elif any(keyword in filename_lower for keyword in ["display", "lcd", "led", "oled"]):
                return "Output"
            elif any(keyword in filename_lower for keyword in ["connector", "header", "pin", "terminal"]):
                return "Connectors"
            elif any(keyword in filename_lower for keyword in ["power", "battery", "voltage", "regulator"]):
                return "Power"
            
            # Try to get category from XML properties
            if properties_elem is not None:
                for prop in properties_elem.findall("property"):
                    if prop.get("name") == "family" and prop.text:
                        return prop.text
            
            # Fallback to directory-based categorization
            if "core" in str(filename):
                return "Core"
            elif "contrib" in str(filename):
                return "Contrib"
            elif "user" in str(filename):
                return "User"
            
            return "Miscellaneous"
        
        # Helper function to get SVG dimensions
        def get_svg_dimensions(svg_content):
            try:
                if not svg_content:
                    return {"width": 72, "height": 93.6}  # Default dimensions
                
                # Try to parse the SVG content
                svg_root = ET.fromstring(svg_content)
                
                # First try to get dimensions from viewBox
                viewbox = svg_root.get("viewBox")
                if viewbox:
                    parts = viewbox.split(" ")
                    if len(parts) >= 4:
                        return {"width": float(parts[2]), "height": float(parts[3])}
                
                # If no viewBox, try width and height attributes
                width = svg_root.get("width")
                height = svg_root.get("height")
                
                if width and height:
                    # Handle units (px, in, etc.)
                    width_value = re.match(r'([\d.]+)([a-z]*)', width)
                    height_value = re.match(r'([\d.]+)([a-z]*)', height)
                    
                    if width_value and height_value:
                        w = float(width_value.group(1))
                        h = float(height_value.group(1))
                        
                        # Convert inches to pixels (assuming 72 DPI)
                        if width_value.group(2) == 'in':
                            w *= 72
                        if height_value.group(2) == 'in':
                            h *= 72
                        
                        return {"width": w, "height": h}
                
                return {"width": 72, "height": 93.6}  # Default dimensions
            except Exception as e:
                logger.warning(f"Error getting SVG dimensions: {e}")
                return {"width": 72, "height": 93.6}  # Default dimensions
        
        # Helper function to parse connector positions from SVG
        def parse_connector_positions(svg_content, connectors):
            if not svg_content or not connectors:
                return connectors
            
            try:
                svg_root = ET.fromstring(svg_content)
                
                # Function to recursively search for elements with matching SVG IDs
                def find_elements_by_svg_id(element, svg_ids_map):
                    results = []
                    
                    # Check if current element has an ID that matches any svgId
                    element_id = element.get("id")
                    if element_id and element_id in svg_ids_map:
                        results.append((element, svg_ids_map[element_id]))
                    
                    # Recursively check children
                    for child in element:
                        results.extend(find_elements_by_svg_id(child, svg_ids_map))
                    
                    return results
                
                # Create a mapping from svgId to connector
                svg_ids_map = {}
                for conn in connectors:
                    svg_id = conn.get("svgId")
                    if svg_id:
                        svg_ids_map[svg_id] = conn
                
                # If no svgIds found, fallback to old matching by connector ID
                if not svg_ids_map:
                    connector_ids = [conn["id"] for conn in connectors]
                    # Use old matching logic as fallback
                    def find_elements_by_id_fallback(element, connector_ids):
                        results = []
                        element_id = element.get("id")
                        if element_id:
                            for conn_id in connector_ids:
                                # Match exact ID or pattern like 'connector0pin' for 'connector0'
                                if element_id == conn_id or (conn_id in element_id and 
                                                            ("pin" in element_id or "pad" in element_id)):
                                    results.append((element, conn_id))
                        for child in element:
                            results.extend(find_elements_by_id_fallback(child, connector_ids))
                        return results
                    
                    matching_elements = find_elements_by_id_fallback(svg_root, connector_ids)
                    # Convert to new format
                    matching_elements = [(elem, next((c for c in connectors if c["id"] == conn_id), None)) 
                                       for elem, conn_id in matching_elements]
                else:
                    # Find elements with matching svgIds
                    matching_elements = find_elements_by_svg_id(svg_root, svg_ids_map)
                
                # Extract positions from matching elements
                for element, connector in matching_elements:
                    if not connector:
                        continue
                    
                    # Extract position based on element type with improved logic
                    x, y = None, None
                    
                    # For circle elements (common for pins)
                    if element.tag.endswith("circle"):
                        x = float(element.get("cx", 0))
                        y = float(element.get("cy", 0))
                    
                    # For rect elements (very common in Fritzing)
                    elif element.tag.endswith("rect"):
                        rect_x = float(element.get("x", 0))
                        rect_y = float(element.get("y", 0))
                        rect_width = float(element.get("width", 0))
                        rect_height = float(element.get("height", 0))
                        # Use center of rectangle for pin position
                        x = rect_x + rect_width / 2
                        y = rect_y + rect_height / 2
                    
                    # For line elements
                    elif element.tag.endswith("line"):
                        x1 = float(element.get("x1", 0))
                        y1 = float(element.get("y1", 0))
                        x2 = float(element.get("x2", 0))
                        y2 = float(element.get("y2", 0))
                        # Use midpoint of line
                        x = (x1 + x2) / 2
                        y = (y1 + y2) / 2
                    
                    # For path elements, try to extract first point
                    elif element.tag.endswith("path"):
                        d = element.get("d", "")
                        if d:
                            # Simple parsing for M (moveto) commands
                            import re
                            match = re.search(r'M\s*([\d.-]+)[\s,]+([\d.-]+)', d)
                            if match:
                                x = float(match.group(1))
                                y = float(match.group(2))
                    
                    # For ellipse elements
                    elif element.tag.endswith("ellipse"):
                        x = float(element.get("cx", 0))
                        y = float(element.get("cy", 0))
                    
                    # For polygon elements, try to find center
                    elif element.tag.endswith("polygon"):
                        points_str = element.get("points", "")
                        if points_str:
                            # Simple center calculation from points
                            points = []
                            try:
                                coords = points_str.replace(",", " ").split()
                                for i in range(0, len(coords)-1, 2):
                                    points.append((float(coords[i]), float(coords[i+1])))
                                if points:
                                    x = sum(p[0] for p in points) / len(points)
                                    y = sum(p[1] for p in points) / len(points)
                            except (ValueError, IndexError):
                                pass
                    
                    # For group elements, try to get transform or use 0,0
                    elif element.tag.endswith("g"):
                        transform = element.get("transform", "")
                        if "translate" in transform:
                            import re
                            match = re.search(r'translate\s*\(\s*([\d.-]+)[\s,]+([\d.-]+)\s*\)', transform)
                            if match:
                                x = float(match.group(1))
                                y = float(match.group(2))
                    
                    # For other elements with direct x,y attributes
                    else:
                        x = float(element.get("x", 0))
                        y = float(element.get("y", 0))
                    
                    # Update connector position if coordinates were found
                    if x is not None and y is not None:
                        connector["x"] = x
                        connector["y"] = y
                        logger.info(f"Updated connector {connector['id']} (svgId: {connector.get('svgId', 'N/A')}) position to ({x}, {y})")
                
                return connectors
            except Exception as e:
                logger.warning(f"Error parsing connector positions: {e}")
                return connectors
        
        # Process all FZP files
        for fzp_file in fritzing_parts_dir.glob("**/*.fzp"):
            try:
                tree = ET.parse(fzp_file)
                root = tree.getroot()
                
                # Extract basic component info
                component_id = len(components) + 1
                fritzingId = fzp_file.stem
                title = root.get("title", fzp_file.stem)
                description = root.get("description", "")
                
                # Get properties element for category extraction
                properties_elem = root.find(".//properties")
                category = extract_category(str(fzp_file), properties_elem)
                
                # Extract tags
                tags = []
                tags_elem = root.find(".//tags")
                if tags_elem is not None:
                    for tag in tags_elem.findall("tag"):
                        if tag.text:
                            tags.append(tag.text)
                
                # Initialize component
                component = {
                    "id": component_id,
                    "fritzingId": fritzingId,
                    "title": title,
                    "description": description,
                    "category": category,
                    "tags": tags,
                    "iconUrl": f"/api/components/{component_id}/svg/icon",
                    "breadboardUrl": f"/api/components/{component_id}/svg/breadboard",
                    "connectors": [],
                    "properties": {},
                    "dimensions": {"width": 72, "height": 93.6}  # Default dimensions
                }
                
                # Extract connectors
                connectors_elem = root.find(".//connectors")
                if connectors_elem is not None:
                    for connector in connectors_elem.findall("connector"):
                        conn_id = connector.get("id", "")
                        conn_name = connector.get("name", conn_id)
                        conn_type = connector.get("type", "male")
                        
                        # Try to get breadboard svgId and position from FZP
                        bb_elem = connector.find(".//p[@layer='breadboard']")
                        x, y = 0, 0
                        svg_id = None
                        
                        if bb_elem is not None:
                            # Get position from FZP if available (fallback)
                            x = float(bb_elem.get("x", 0))
                            y = float(bb_elem.get("y", 0))
                            # Get the SVG ID that corresponds to this connector in the breadboard view
                            svg_id = bb_elem.get("svgId")
                        
                        component["connectors"].append({
                            "id": conn_id,
                            "name": conn_name,
                            "x": x,
                            "y": y,
                            "type": conn_type,
                            "svgId": svg_id  # Add svgId for proper SVG matching
                        })
                
                # Extract properties
                if properties_elem is not None:
                    for prop in properties_elem.findall("property"):
                        prop_name = prop.get("name")
                        if prop_name and prop.text:
                            component["properties"][prop_name] = prop.text
                
                # Get SVG content for dimensions and connector positions
                svg_filename = f"{fritzingId}.svg"
                svg_paths = [
                    fritzing_parts_dir / "svg" / "core" / "breadboard" / svg_filename,
                    fritzing_parts_dir / "svg" / "contrib" / "breadboard" / svg_filename,
                    fritzing_parts_dir / "svg" / "user" / "breadboard" / svg_filename,
                    fritzing_parts_dir / "svg" / "obsolete" / "breadboard" / svg_filename
                ]
                
                svg_content = None
                for svg_path in svg_paths:
                    if svg_path.exists():
                        with open(svg_path, "r", encoding="utf-8") as f:
                            svg_content = f.read()
                        break
                
                if svg_content:
                    # Get SVG dimensions
                    component["dimensions"] = get_svg_dimensions(svg_content)
                    
                    # Update connector positions from SVG
                    component["connectors"] = parse_connector_positions(svg_content, component["connectors"])
                
                components.append(component)
            except Exception as e:
                logger.warning(f"Failed to parse {fzp_file}: {e}")
                continue
        
        return {"success": True, "components": components}
    except Exception as e:
        logger.error(f"Error fetching components: {e}")
        return {"success": False, "error": str(e)}

@api_router.get("/components/{component_id}/svg/{svg_type}")
async def get_component_svg(component_id: int, svg_type: str):
    """Get component SVG for breadboard/schematic view with proper dimensions and scaling"""
    try:
        from fastapi.responses import Response
        import os
        from pathlib import Path
        import xml.etree.ElementTree as ET
        
        # Get the component from the list
        components = []
        fritzing_parts_dir = ROOT_DIR / "fritzing-parts"
        
        if not fritzing_parts_dir.exists():
            raise FileNotFoundError("Fritzing parts directory not found")
        
        # Find the component with the given ID
        component = None
        component_count = 0
        
        for fzp_file in fritzing_parts_dir.glob("**/*.fzp"):
            component_count += 1
            if component_count == component_id:
                try:
                    tree = ET.parse(fzp_file)
                    root = tree.getroot()
                    component = {
                        "id": component_id,
                        "fritzingId": fzp_file.stem,
                        "path": fzp_file,
                        "title": root.get("title", fzp_file.stem),
                        "dimensions": {"width": 72, "height": 93.6}  # Default dimensions
                    }
                    break
                except Exception as e:
                    logger.warning(f"Failed to parse {fzp_file}: {e}")
        
        if not component:
            # Fallback to placeholder if component not found
            placeholder_svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="64" height="64" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
    <rect x="4" y="4" width="56" height="56" fill="#666" stroke="#333" stroke-width="2" rx="4"/>
    <text x="32" y="35" text-anchor="middle" fill="white" font-size="10">C{component_id}</text>
</svg>'''
            return Response(content=placeholder_svg, media_type="image/svg+xml")
        
        # Determine the SVG path based on the component and view type
        svg_filename = f"{component['fritzingId']}.svg"
        
        # Check in different possible locations
        svg_paths = [
            fritzing_parts_dir / "svg" / "core" / svg_type / svg_filename,
            fritzing_parts_dir / "svg" / "contrib" / svg_type / svg_filename,
            fritzing_parts_dir / "svg" / "user" / svg_type / svg_filename,
            fritzing_parts_dir / "svg" / "obsolete" / svg_type / svg_filename
        ]
        
        svg_content = None
        svg_path_found = None
        for svg_path in svg_paths:
            if svg_path.exists():
                with open(svg_path, "r", encoding="utf-8") as f:
                    svg_content = f.read()
                svg_path_found = svg_path
                break
        
        if not svg_content:
            # Fallback to placeholder if SVG not found
            width = component.get("dimensions", {}).get("width", 64)
            height = component.get("dimensions", {}).get("height", 64)
            title = component.get("title", f"C{component_id}")
            placeholder_svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
    <rect x="4" y="4" width="{width-8}" height="{height-8}" fill="#666" stroke="#333" stroke-width="2" rx="4"/>
    <text x="{width/2}" y="{height/2}" text-anchor="middle" fill="white" font-size="10">{title}</text>
</svg>'''
            return Response(content=placeholder_svg, media_type="image/svg+xml")
        
        # Process the SVG to ensure it has proper dimensions and viewBox
        try:
            # Parse the SVG
            svg_root = ET.fromstring(svg_content)
            
            # Get or set dimensions
            width = component.get("dimensions", {}).get("width", 72)
            height = component.get("dimensions", {}).get("height", 93.6)
            
            # Check if SVG has viewBox attribute
            viewbox = svg_root.get("viewBox")
            if not viewbox:
                # If no viewBox, create one based on width and height
                svg_root.set("viewBox", f"0 0 {width} {height}")
            
            # Ensure width and height attributes are set
            svg_root.set("width", str(width))
            svg_root.set("height", str(height))
            
            # Convert back to string
            svg_content = ET.tostring(svg_root, encoding="unicode")
        except Exception as e:
            logger.warning(f"Error processing SVG dimensions: {e}")
            # Continue with original SVG if processing fails
            pass
        
        return Response(content=svg_content, media_type="image/svg+xml")
    except Exception as e:
        logger.error(f"Error fetching component SVG: {e}")
        # Return placeholder on error
        placeholder_svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="64" height="64" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
    <rect x="4" y="4" width="56" height="56" fill="#666" stroke="#333" stroke-width="2" rx="4"/>
    <text x="32" y="35" text-anchor="middle" fill="white" font-size="10">Error</text>
</svg>'''
        return Response(content=placeholder_svg, media_type="image/svg+xml")

@api_router.post("/components/load")
async def load_components():
    """Load Fritzing components"""
    try:
        # This endpoint is just a placeholder to match the frontend's expectation
        # The actual component loading happens in the GET /components endpoint
        return {"success": True, "message": "Components loaded successfully"}
    except Exception as e:
        logger.error(f"Error loading components: {e}")
        return {"success": False, "error": str(e)}

@api_router.post("/save-svg")
async def save_svg(request: Request):
    """Save circuit design as SVG"""
    try:
        data = await request.json()
        svg_content = data.get("svg")
        file_name = data.get("fileName", "circuit.svg")
        
        if not svg_content:
            return {"success": False, "error": "No SVG content provided"}
        
        # Ensure the file has .svg extension
        if not file_name.lower().endswith(".svg"):
            file_name += ".svg"
        
        # Create the path within arduino_workspace
        workspace_dir = Path(os.path.join(os.environ.get('TEMP', os.path.join(ROOT_DIR, 'temp')), "arduino_workspace"))
        file_path = workspace_dir / file_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write the SVG content to the file
        with open(file_path, "w") as f:
            f.write(svg_content)
        
        logger.info(f"SVG file saved successfully: {file_path}")
        return {"success": True, "path": str(file_path)}
    except Exception as e:
        logger.error(f"Error saving SVG file: {e}")
        return {"success": False, "error": str(e)}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_event():
    # Cleanup resources if needed
    pass
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####
#
#  This code is based on the Blenderkit Addon
#  Homepage: https://www.blenderkit.com/
#  Sourcecode: https://github.com/blender/blender-addons/tree/master/blenderkit
#
# #####
#
#  This code is based on the Blenderkit Addon
#  Homepage: https://www.blenderkit.com/
#  Sourcecode: https://github.com/blender/blender-addons/tree/master/blenderkit
#
# #####

import bpy
import uuid
from os.path import basename, dirname
import hashlib
import tempfile
import os
import urllib.error
from mathutils import Vector, Matrix
import threading
from threading import _MainThread, Thread
from ...handlers.lol.timer import timer_update
from ...utils import get_addon_preferences, compatibility
from ...utils.errorlog import LuxCoreErrorLog

LOL_HOST_URL = "https://luxcorerender.org/lol"

download_threads = []

def download_table_of_contents(context):
    scene = context.scene

    try:
        import urllib.request
        with urllib.request.urlopen(LOL_HOST_URL + "/assets_model.json", timeout=60) as request:
            import json
            scene.luxcoreOL.model['assets'] = json.loads(request.read())
            for asset in scene.luxcoreOL.model['assets']:
                asset['downloaded'] = 0.0

            # with urllib.request.urlopen(LOL_HOST_URL + "/assets_scene.json", timeout=60) as request:
            #     import json
            #     scene.luxcoreOL.scene['assets'] = json.loads(request.read())
            #     for asset in scene.luxcoreOL.scene['assets']:
            #         asset['downloaded'] = 0.0

            with urllib.request.urlopen(LOL_HOST_URL + "/assets_material.json", timeout=60) as request:
                import json
                scene.luxcoreOL.material['assets'] = json.loads(request.read())
                for asset in scene.luxcoreOL.material['assets']:
                    asset['downloaded'] = 0.0

        context.scene.luxcoreOL.ui.ToC_loaded = True
        init_categories(context)
        bg_task = Thread(target=check_cache, args=(context, ))
        bg_task.start()
        return True
    except ConnectionError as error:
        print("Connection error: Could not download table of contents")
        print(error)
        return False
    except urllib.error.URLError as error:
        print("URL error: Could not download table of contents")
        print(error)
        return False


def init_categories(context):
    scene = context.scene
    ui_props = scene.luxcoreOL.ui
    assets = get_search_props(context)
    categories = {}

    for asset in assets:
        cat = asset['category']
        try:
            categories[cat] += 1
        except KeyError:
            categories[cat] = 1

    if ui_props.asset_type == 'MODEL':
        asset_props = scene.luxcoreOL.model
    if ui_props.asset_type == 'SCENE':
        asset_props = scene.luxcoreOL.scene
    if ui_props.asset_type == 'MATERIAL':
        asset_props = scene.luxcoreOL.material

    asset_props['categories'] = categories


def check_cache(args):
    (context) = args
    name = basename(dirname(dirname(dirname(__file__))))
    user_preferences = context.preferences.addons[name].preferences

    scene = context.scene
    assets = scene.luxcoreOL.model['assets']
    for asset in assets:
        filename = asset["url"]
        filepath = os.path.join(user_preferences.global_dir, "model", filename[:-3] + 'blend')

        if os.path.exists(filepath):
            if calc_hash(filepath) == asset["hash"]:
                asset['downloaded'] = 100.0

    # assets = scene.luxcoreOL.scene['assets']
    # for asset in assets:
    #     filename = asset["url"]
    #     filepath = os.path.join(user_preferences.global_dir, "scene", filename[:-3] + 'blend')
    #
    #     if os.path.exists(filepath):
    #         if calc_hash(filepath) == asset["hash"]:
    #             asset['downloaded'] = 100.0

    assets = scene.luxcoreOL.material['assets']
    for asset in assets:
        filename = asset["url"]
        filepath = os.path.join(user_preferences.global_dir, "material", filename[:-3] + 'blend')

        if os.path.exists(filepath):
            if calc_hash(filepath) == asset["hash"]:
                asset['downloaded'] = 100.0


def calc_hash(filename):
    BLOCK_SIZE = 65536
    file_hash = hashlib.sha256()
    with open(filename, 'rb') as file:
        block = file.read(BLOCK_SIZE)
        while len(block) > 0:
            file_hash.update(block)
            block = file.read(BLOCK_SIZE)
    return file_hash.hexdigest()


def is_downloading(asset):
    global download_threads
    for thread_data in download_threads:
        if thread_data[2].passargs['thumbnail']:
            continue
        if asset['hash'] == thread_data[1]['hash']:
            # print(asset["name"], "is downloading")
            return thread_data[2]
    return None


def download_file(asset_type, asset, location, rotation, target_object, target_slot):
    downloader = {'location': (location[0],location[1],location[2]), 'rotation': (rotation[0],rotation[1],rotation[2]),
                  'target_object': target_object, 'target_slot': target_slot}
    tcom = is_downloading(asset)
    if tcom is None:
        tcom = ThreadCom()
        tcom.passargs['downloaders'] = [downloader]
        tcom.passargs['thumbnail'] = False
        tcom.passargs['asset type'] = asset_type
        asset_data = asset.to_dict()

        downloadthread = Downloader(asset_data, tcom)

        download_threads.append([downloadthread, asset_data, tcom])
        bpy.app.timers.register(timer_update)
    else:
        tcom.passargs['downloaders'].append(downloader)

    return True

class Downloader(threading.Thread):
    def __init__(self, asset, tcom):
        super(Downloader, self).__init__()
        self.asset = asset
        self.tcom = tcom
        self._stop_event = threading.Event()

    def stop(self):
        # print("Download Thread stopped")
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    # def main_download_thread(asset_data, tcom, scene_id, api_key):
    def run(self):
        import urllib.request
        user_preferences = get_addon_preferences(bpy.context)

        # print("Download Thread running")
        tcom = self.tcom

        if tcom.passargs['thumbnail']:
            # Thumbnail  download
            imagename = self.asset['url'][:-4] + '.jpg'
            thumbnailpath = os.path.join(user_preferences.global_dir, tcom.passargs['asset type'].lower(), "preview",
                                         imagename)
            url = LOL_HOST_URL + "/" + tcom.passargs['asset type'].lower() + "/preview/" + imagename
            try:
                with urllib.request.urlopen(url, timeout=60) as url_handle, open(thumbnailpath, "wb") as file_handle:
                    file_handle.write(url_handle.read())

                imgname = self.asset['thumbnail']
                img = bpy.data.images.load(thumbnailpath)
                img.name = imgname
                img.colorspace_settings.name = 'Linear'

                tcom.finished = True

            except ConnectionError as error:
                print("Connection error: Could not download " + imagename)
                print(error)
            except urllib.error.HTTPError as error:
                print("HTTPError error: Could not download " + imagename)
                print(error)
        else:
            #Asset download
            filename = self.asset["url"]

            with tempfile.TemporaryDirectory() as temp_dir_path:
                temp_zip_path = os.path.join(temp_dir_path, filename)
                url = LOL_HOST_URL + "/" + tcom.passargs['asset type'].lower() + "/" + filename
                try:
                    print("Downloading:", url)

                    with urllib.request.urlopen(url, timeout=60) as url_handle, \
                            open(temp_zip_path, "wb") as file_handle:
                        total_length = url_handle.headers.get('Content-Length')
                        tcom.file_size = int(total_length)

                        dl = 0
                        data = url_handle.read(8192)
                        file_handle.write(data)
                        while len(data) == 8192:
                            data = url_handle.read(8192)
                            dl += len(data)
                            tcom.downloaded = dl
                            tcom.progress = int(100 * tcom.downloaded / tcom.file_size)

                            # Stop download if Blender is closed
                            for thread in threading.enumerate():
                                if isinstance(thread, _MainThread):
                                    if not thread.is_alive():
                                        self.stop()

                            file_handle.write(data)
                            if self.stopped():
                                url_handle.close()
                                return
                    print("Download finished")
                    import zipfile
                    with zipfile.ZipFile(temp_zip_path) as zf:
                        print("Extracting zip to", os.path.join(user_preferences.global_dir, tcom.passargs['asset type'].lower()))
                        zf.extractall(os.path.join(user_preferences.global_dir, tcom.passargs['asset type'].lower()))
                    tcom.finished = True

                except urllib.error.URLError as err:
                    print("Could not download: %s" % err)


class ThreadCom:  # object passed to threads to read background process stdout info
    def __init__(self):
        self.file_size = 1000000000000000  # property that gets written to.
        self.downloaded = 0
        self.progress = 0.0
        self.finished = False
        self.passargs = {}


def link_asset(context, asset, location, rotation):
    name = basename(dirname(dirname(dirname(__file__))))
    user_preferences = context.preferences.addons[name].preferences

    filename = asset["url"]
    filepath = os.path.join(user_preferences.global_dir, "model", filename[:-3] + 'blend')

    scene = context.scene
    link_model = (scene.luxcoreOL.model.append_method == 'LINK_COLLECTION')

    with bpy.data.libraries.load(filepath, link=link_model) as (data_from, data_to):
        data_to.objects = [name for name in data_from.objects if name not in ["Plane", "Camera"]]

    bbox_min = asset["bbox_min"]
    bbox_max = asset["bbox_max"]
    bbox_center = 0.5 * Vector((bbox_max[0] + bbox_min[0], bbox_max[1] + bbox_min[1], 0.0))

    # TODO: Check if asset is already used in scene and override append/link selection
    # If the same model is first linked and then appended it breaks relationships and transformaton in blender

    # Add new collection, where the assets are placed into
    col = bpy.data.collections.new(asset["name"])

    # Add parent empty for asset collection
    main_object = bpy.data.objects.new(asset["name"], None)
    main_object.empty_display_size = 0.5 * max(bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1],
                                               bbox_max[2] - bbox_min[2])

    main_object.location = location
    main_object.rotation_euler = rotation
    main_object.empty_display_size = 0.5*max(bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1], bbox_max[2] - bbox_min[2])

    if link_model:
        main_object.instance_type = 'COLLECTION'
        main_object.instance_collection = col
        col.instance_offset = bbox_center
    else:
        scene.collection.children.link(col)

    scene.collection.objects.link(main_object)

    # Objects have to be linked to show up in a scene
    for obj in data_to.objects:
        if not link_model:
            obj.data.make_local()
            parent = obj
            while parent.parent != None:
                parent = parent.parent

            if parent != main_object:
                parent.parent = main_object
                parent.matrix_parent_inverse = main_object.matrix_world.inverted() @ Matrix.Translation(-1*bbox_center)

        # Add objects to asset collection
        col.objects.link(obj)
        compatibility.run()


def append_material(context, asset, target_object, target_slot):
    if target_object == None:
        return

    name = basename(dirname(dirname(dirname(__file__))))
    user_preferences = context.preferences.addons[name].preferences

    filename = asset["url"]
    filepath = os.path.join(user_preferences.global_dir, "material", filename[:-3] + 'blend')

    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        data_to.materials = [name for name in data_from.materials if name == asset["name"]]

    if len(data_to.materials) == 1:
        # print(target_object, target_slot, data_to.materials[0].name)
        if len(bpy.data.objects[target_object].material_slots) == 0:
            bpy.data.objects[target_object].data.materials.append(data_to.materials[0])
        else:
            if bpy.data.objects[target_object].library == None:
                bpy.data.objects[target_object].material_slots[target_slot].material = data_to.materials[0]
        compatibility.run()



def load_asset(context, asset, location, rotation, target_object, target_slot):
    name = basename(dirname(dirname(dirname(__file__))))
    user_preferences = context.preferences.addons[name].preferences

    ui_props = context.scene.luxcoreOL.ui

    #TODO: write method for this as it is used serveral times
    if ui_props.asset_type == 'SCENE':
        filename = asset["url"]
        filepath = os.path.join(user_preferences.global_dir, "model", filename[:-3] + 'blend')
    else:
        filename = asset["url"]
        filepath = os.path.join(user_preferences.global_dir, ui_props.asset_type.lower(), filename[:-3] + 'blend')

    ''' Check if model is cached '''
    download = False
    if not os.path.exists(filepath):
        download = True
    else:
        hash = calc_hash(filepath)
        if hash != asset["hash"]:
            print("hash number doesn't match: %s" % hash)
            download = True

    if download:
        print("Download asset")
        download_file(ui_props.asset_type, asset, location, rotation, target_object, target_slot)
    else:
        if ui_props.asset_type == 'MATERIAL':
            append_material(context, asset, target_object, target_slot)
        else:
            link_asset(context, asset, location, rotation)


def get_search_props(context):
    scene = context.scene
    if scene is None:
        return
    ui_props = scene.luxcoreOL.ui
    props = None

    if ui_props.asset_type == 'MODEL':
        if not 'assets' in scene.luxcoreOL.model:
            return
        props = scene.luxcoreOL.model['assets']
    if ui_props.asset_type == 'SCENE':
        if not 'assets' in scene.luxcoreOL.scene:
            return
        props = scene.luxcoreOL.scene['assets']
    if ui_props.asset_type == 'MATERIAL':
        if not 'assets' in scene.luxcoreOL.material:
            return
        props = scene.luxcoreOL.material['assets']

    # if ui_props.asset_type == 'TEXTURE':
    #     if not hasattr(scene.luxcoreOL.texture, 'assets'):
    #         return
    #     props = scene.luxcoreOL.texture['assets']

    # if ui_props.asset_type == 'BRUSH':
    #     if not hasattr(scene.luxcoreOL, 'brush'):
    #         return
    #     props = scene.luxcoreOL.brush['assets']
    return props


def save_prefs(self, context):
    # first check context, so we don't do this on registration or blender startup
    if not bpy.app.background: #(hasattr kills blender)
        name = basename(dirname(dirname(dirname(__file__))))
        user_preferences = context.preferences.addons[name].preferences
        # TODO: Implement
        test = 1
        #prefs = {
        #    'global_dir': user_preferences.global_dir,
        #}
        #try:
        #    fpath = paths.BLENDERKIT_SETTINGS_FILENAME
        #    if not os.path.exists(paths._presets):
        #        os.makedirs(paths._presets)
        #    f = open(fpath, 'w')
        #    with open(fpath, 'w') as s:
        #        import json
        #        json.dump(prefs, s)
        #except Exception as e:
        #    print(e)


def get_default_directory():
    from os.path import expanduser
    home = expanduser("~")
    return home + os.sep + 'LuxCoreOnlineLibrary_data'


def get_scene_id():
    '''gets scene id and possibly also generates a new one'''
    bpy.context.scene['uuid'] = bpy.context.scene.get('uuid', str(uuid.uuid4()))
    return bpy.context.scene['uuid']


def guard_from_crash():
    '''Blender tends to crash when trying to run some functions with the addon going through unregistration process.'''
    #if bpy.context.preferences.addons.get('BlendLuxCore') is None:
    #    return False
    #if bpy.context.preferences.addons['BlendLuxCore'].preferences is None:
    #    return False
    return True


def download_thumbnail(self, context, asset, index):
    ui_props = context.scene.luxcoreOL.ui

    tcom = is_downloading(asset)
    if tcom is None:
        tcom = ThreadCom()
        tcom.passargs['thumbnail'] = True
        tcom.passargs['asset type'] = ui_props.asset_type

        downloadthread = Downloader(asset, tcom)

        download_threads.append([downloadthread, asset, tcom])
        bpy.app.timers.register(timer_update)


    return True


def get_thumbnail(imagename):
    name = dirname(dirname(dirname(__file__)))
    path = os.path.join(name, 'thumbnails', imagename)

    imagename = '.%s' % imagename
    img = bpy.data.images.get(imagename)

    if img == None:
        img = bpy.data.images.load(path)
        img.colorspace_settings.name = 'Linear'
        img.name = imagename
        img.name = imagename

    return img


def previmg_name(index, fullsize=False):
    if not fullsize:
        return '.LOL_preview_'+ str(index).zfill(2)
    else:
        return '.LOL_preview_full_' + str(index).zfill(2)


def load_previews(context, assets):
    name = basename(dirname(dirname(dirname(__file__))))
    user_preferences = context.preferences.addons[name].preferences
    ui_props = context.scene.luxcoreOL.ui

    if assets is not None and len(assets) != 0:
        i = 0
        for asset in assets:
            if ui_props.asset_type == 'MATERIAL':
                tpath = os.path.join(user_preferences.global_dir, ui_props.asset_type.lower(), "preview",
                                     asset['name'] + '.jpg')
            else:
                tpath = os.path.join(user_preferences.global_dir, ui_props.asset_type.lower(), "preview", asset['url'][:-4] + '.jpg')
            imgname = previmg_name(i)

            asset["thumbnail"] = imgname
            if os.path.exists(tpath):
                img = bpy.data.images.get(imgname)
                if img is None or img.size[0] == 0:
                    img = bpy.data.images.load(tpath)
                    img.name = imgname
                elif img.filepath != tpath:
                    # had to add this check for autopacking files...
                    if img.packed_file is not None:
                        img.unpack(method='USE_ORIGINAL')
                    img.filepath = tpath
                    img.reload()
                img.colorspace_settings.name = 'Linear'
            else:
                if imgname in bpy.data.images:
                    img = bpy.data.images[imgname]
                    bpy.data.images.remove(img)
                # print('Thumbnail not cached: ', imgname)
                download_thumbnail(None, context, asset, i)

            i += 1

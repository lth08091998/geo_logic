#!/usr/bin/python3

from geo_object import *
from tool_step import ToolStep
from movable_tools import Intersection
import itertools

def run_tuple(f, *args):
    if isinstance(f, tuple):
        args += f[1:]
        f = f[0]
    f(*args)

"""
ObjSelector is a class for finding an object in the picture by coordinates
the result is a pair (graphical_index, numerical_representation).
The graphical_index determines e.g. the name of the object, see graphical_env.py.
"""
class ObjSelector:
    def __init__(self):
        self.find_radius_pix = 20 # radius for selection in pixels
    def _update_find_radius(self):
        self.find_radius = self.find_radius_pix / self.viewport.scale

    # find object from a given list
    def coor_to_obj(self, coor, l, filter_f = None):
        self._update_find_radius()
        if filter_f is not None:
            l = ((obj,objn) for (obj,objn) in l if filter_f(obj, objn))
        candidates = (
            (objn.dist_from(coor), obj, objn)
            for (obj,objn) in l
        )
        d,obj,objn = min(candidates, key = lambda x: x[0], default = (0,None,None))
        if d >= self.find_radius: return None, None
        return obj, objn

    def coor_to_point(self, coor, **kwargs):
        return self.coor_to_obj(coor, self.vis.selectable_points, **kwargs)
    def coor_to_line(self, coor, **kwargs):
        return self.coor_to_obj(coor, self.vis.selectable_lines, **kwargs)
    def coor_to_circle(self, coor, **kwargs):
        return self.coor_to_obj(coor, self.vis.selectable_circles, **kwargs)
    def coor_to_cl(self, coor, **kwargs):
        return self.coor_to_obj(
            coor,
            itertools.chain(self.vis.selectable_lines,self.vis.selectable_circles),
            **kwargs
        )
    # sequential attempts of coor_to_*
    def coor_to_attempts(self, coor, *selectors, **kwargs):
        for selector in selectors:
            obj,objn = selector(coor, **kwargs)
            if obj is not None: return obj,objn
        return None,None
    def coor_to_pcl(self, coor, **kwargs):
        return self.coor_to_attempts(coor, self.coor_to_point, self.coor_to_cl, **kwargs)
    def coor_to_pl(self, coor, **kwargs):
        return self.coor_to_attempts(coor, self.coor_to_point, self.coor_to_line, **kwargs)
    def coor_to_pc(self, coor, **kwargs):
        return self.coor_to_attempts(coor, self.coor_to_point, self.coor_to_circle, **kwargs)

    # when activated
    def enter(self, viewport):
        self.viewport = viewport
        self.env = viewport.env
        self.vis = viewport.vis
    # when deactivated
    def leave(self):
        pass

"""
HighlightList is a general class for extra gui elements
(selections, helpers, proposals) drawn by the gtool.
These elements are often build incrementaly,
but some are permanent (already selected items), others are
temporary (the current object under mouse).

Therefore, there is the saved list of the permanent object
(the initial setting before investigating mouse cursor), and
the current list l. When confirmed (click), the current list
becomes the initial list depending on whether the new objects
were added with the "permanent" attribute.
"""
class HighlightList:
    def __init__(self):
        self.l = []
        self.saved = []
    def to_list(self):
        return [x for (x,permanent) in self.l]
    def add(self, *args, permanent = False):
        self.l.extend((arg, permanent) for arg in args)
    def load(self):
        self.l = list(self.ini)
    def save(self):
        self.ini = [x for x in self.l if x[1]]
    def reset_save(self): self.ini = []
    def pop(self): return self.l.pop()
    def remove(self, x): return self.l.remove((x, True))
    def remove_if(self, cond):
        self.l = [
            (x,perm) for (x,perm) in self.l if not cond(x)
        ]

"""
The main class for a GUI Tool is GTool, its descendants are used for all the GUI tools
such as point, parallel, move, hide, ...

At every point, there is an update function which is called primarily on mouse movement.
The update function takes the current mouse coordinates (in geometrical coordinates), and
potentionally further extra parameters. It searches for interesting
objects under the mouse cursor and determines what should be done with them.

At the beginning (or after tool restart), the update function is set to be "self.update_basic".
The update function can update the hl_* lists (typically by calling hl_propose, hl_select, hl_add_helper),
and set the following attributes
  * self.confirm = function (possibly with arguments) that should be called after click
  * self.confirm_next = the next update function after a click (if not set, the tool is reseted after click)
  * self.drag_start = function called on clicking followed by a drag
  * self.drag = update function during dragging (if not set, dragging is disabled)
"""
class GTool(ObjSelector):
    icon_name = None
    key_shortcut = None
    label = None
    def get_icon_name(self): return self.icon_name
    def get_cursor(self): return self.icon_name
    def get_key_shortcut(self): return self.key_shortcut
    def get_label(self):
        return "{} ({})".format(self.label, self.key_shortcut.upper())

    def __init__(self):
        ObjSelector.__init__(self)
        self.distance_to_drag_pix = 5
        self.hl_proposals = HighlightList()
        self.hl_selected = HighlightList()
        self.hl_helpers = HighlightList()
        self.hl_lists = [self.hl_proposals, self.hl_selected, self.hl_helpers]

    def reset(self): # called for example on right click
        self.dragged = False
        self.click_coor = None

        self._hl_reset()
        self._pre_update()
        self._hl_update()
        self.update = self.update_basic
        run_tuple(self.on_reset)

    ### basic manipulation with additional GUI elements
    def _hl_reset(self):
        for hl_list in self.hl_lists: hl_list.reset_save()
    def _hl_load(self):
        for hl_list in self.hl_lists: hl_list.load()
    def _hl_save(self):
        for hl_list in self.hl_lists: hl_list.save()
    def _hl_update(self):
        self.vis.update_hl_selected(self.hl_selected.to_list())
        self.vis.update_hl_proposals(self.hl_proposals.to_list())
        self.vis.update_hl_helpers(self.hl_helpers.to_list())

    def cursor_away(self):
        self._hl_load()
        self._hl_update()

    # object selection -- combining ObjSelector and HighlightList hl_selected
    # the selected object is returned and also added to self.hl_selected
    def select_by_coor(self, coor, coor_to_x, permanent = True, **kwargs):
        obj,nobj = coor_to_x(coor, **kwargs)
        if obj is not None: self.hl_select(obj, permanent = permanent)
        return obj,nobj
    def select_point(self, coor, **kwargs):
        return self.select_by_coor(coor, self.coor_to_point, **kwargs)
    def select_line(self, coor, **kwargs):
        return self.select_by_coor(coor, self.coor_to_line, **kwargs)
    def select_circle(self, coor, **kwargs):
        return self.select_by_coor(coor, self.coor_to_circle, **kwargs)
    def select_cl(self, coor, **kwargs):
        return self.select_by_coor(coor, self.coor_to_cl, **kwargs)
    def select_pcl(self, coor, **kwargs):
        return self.select_by_coor(coor, self.coor_to_pcl, **kwargs)
    def select_pl(self, coor, **kwargs):
        return self.select_by_coor(coor, self.coor_to_pl, **kwargs)
    def select_pc(self, coor, **kwargs):
        return self.select_by_coor(coor, self.coor_to_pc, **kwargs)

    def _pre_update(self):
        self._hl_load()
        self._update_find_radius()
        self.drag = None
        self.drag_start = None
        self.confirm = None
        self.confirm_next = None

    def hl_propose(self, *args, **kwargs):
        self.hl_proposals.add(*args, **kwargs)
    def hl_select(self, *args, **kwargs):
        self.hl_selected.add(*args, **kwargs)
    def hl_add_helper(self, *args, **kwargs):
        self.hl_helpers.add(*args, **kwargs)

    # function executed primarily on mouse movement
    def _run_update(self, coor):
        self._pre_update()
        run_tuple(self.update, coor)
        self._hl_update()

    # function executted primarily on click (or drag release)
    def _run_confirm(self):
        if self.confirm is not None:
            run_tuple(self.confirm)
        if self.confirm_next is not None:
            self.update = self.confirm_next
            self._hl_save()
        else:
            self._hl_reset()
            self.update = self.update_basic
            run_tuple(self.on_reset)

    ### externally called functions

    def button_press(self, coor):
        if self.click_coor is not None: self.reset()
        self._run_update(coor)
        if self.drag is None:
            self._run_confirm()
            self._run_update(coor)
        else:
            self.click_coor = coor
            self.dragged = False
            if self.drag_start is not None:
                run_tuple(self.drag_start)
            self._hl_save()
    def button_release(self, coor):
        if self.click_coor is not None:
            click_coor = self.click_coor
            self.click_coor = None
            self.dragged = False
            self._run_confirm()
        self._run_update(coor)
    def motion(self, coor, button_pressed):
        if self.click_coor is not None:
            if not button_pressed:
                self.reset()
            elif not self.dragged:
                if np.linalg.norm(coor - self.click_coor) >= \
                   self.distance_to_drag_pix / self.viewport.scale:
                    assert(self.drag is not None)
                    self.update = self.drag
                    self.dragged = True

        if self.click_coor is None or self.dragged:
            self._run_update(coor)

    ### helpers for further descendants for interacting with the logic

    def lies_on(self, p, cl):
        p_li = self.vis.gi_to_li(p)
        cl_li = self.vis.gi_to_li(cl)
        if self.vis.li_to_type(cl_li) == Line: label = self.tools.lies_on_l
        else: label = self.tools.lies_on_c
        return self.vis.logic.get_constr(label, (p_li, cl_li)) is not None

    def instantiate_obj(self, obj):
        if isinstance(obj, tuple):
            cmd, *args = obj
            if callable(cmd): obj, = cmd(*args, update = False)
            elif isinstance(cmd, str):
                obj, = self.run_tool(cmd, *args, update = False)
            else: raise Exception("Unexpected command: {}".format(cmd))
        return obj
    def run_tool(self, tool, *args, update = True):
        args = tuple(map(self.instantiate_obj, args))
        if isinstance(tool, str):
            arg_types = tuple(self.vis.gi_to_type(x) for x in args)
            tool = self.tools[tool, arg_types]
        step = ToolStep(tool, (), args, len(self.env.gi_to_step_i))
        return self.env.add_step(step, update = update)
    def run_m_tool(self, name, res_obj, *args, update = True):
        args = tuple(map(self.instantiate_obj, args))
        num_args = tuple(self.vis.gi_to_num(x) for x in args)
        arg_types = tuple(type(x) for x in num_args)
        out_type = type(res_obj)
        tool = self.tools.m[name, arg_types, out_type]
        hyper_params = tool.get_hyperpar(res_obj, *num_args)
        step = ToolStep(tool, hyper_params, args, len(self.env.gi_to_step_i))
        #if name == "intersection":
        #    print(arg_types, hyper_params)
        return self.env.add_step(step, update = update)

    ### extended methods of ObjSelector

    def enter(self, viewport):
        ObjSelector.enter(self, viewport)
        self.tools = self.env.tools
        self.reset()
    def leave(self):
        self.reset()
        ObjSelector.leave(self)

    # to be implemented
    def on_reset(self):
        pass # on right click, unexpected click, or other case of reseting to the default state
    def update_basic(self, coor):
        pass # investigating  in the default (starting) phase


### Simple GTools


# dummy GTool, when no tool is selected
class GToolNone:
    def get_icon_name(self): return None
    def get_cursor(self): return None
    def get_key_shortcut(self): return None
    def get_label(self): return None
    def reset(self): pass
    def cursor_away(self): pass
    def button_press(self, coor): pass
    def button_release(self, coor): pass
    def motion(self, coor, button_pressed): pass
    def enter(self, viewport): pass
    def leave(self): pass

# applied during holding shift
class AmbiSelect(ObjSelector):

    def click(self, coor, rev):
        obj,_ = self.coor_to_pcl(coor)
        if obj is None: return
        direction = 1 if rev else -1
        self.vis.swap_priorities(obj, direction)

    def enter(self, viewport):
        ObjSelector.enter(self, viewport)
        self.vis.ambi_select_mode = True
        self.vis.visible_export()
    def leave(self):
        self.vis.ambi_select_mode = False
        self.vis.visible_export()
        ObjSelector.leave(self)

class GToolMove(GTool):
    icon_name = "move"
    key_shortcut = 'm'
    label = "Move Tool"
    def get_cursor(self):
        if self.click_coor is None: return "grab"
        else: return "grabbing"

    def __init__(self):
        GTool.__init__(self)
        self.distance_to_drag_pix = 0

    def update_basic(self, coor):
        obj,objn = self.select_pcl(coor, permanent = False)
        if obj is None: return

        step = self.env.gi_to_step(obj)
        num_args = tuple(self.vis.gi_to_num(gi) for gi in step.local_args)
        num_res = self.vis.gi_to_num(obj),
        grasp = step.tool.get_grasp(coor, *num_args+num_res)
        self.drag = self.move_obj, step, grasp, num_args
        self.drag_start = self.move_start

    def move_start(self):
        self.viewport.set_cursor_by_tool()
        self.on_reset = self.viewport.set_cursor_by_tool

    def move_obj(self, coor, step, grasp, num_args):
        tool = step.tool
        step.hyper_params = tool.new_hyperpar(grasp, coor, *num_args)
        if isinstance(tool, Intersection):
            intersections = tool.ordered_candidates(num_args)
            i, = step.hyper_params
            self.hl_propose(Point(intersections[1-i]))
        self.env.refresh_steps(catch_errors = True)
        self.env.update_hyperpar_hook(step)

    def enter(self, viewport):
        ObjSelector.enter(self, viewport)
        self.reset()
        self.vis.move_mode = True
        self.vis.refresh()
    def leave(self):
        self.vis.move_mode = False
        self.vis.refresh()        
        GTool.leave(self)

class GToolHide(GTool):

    icon_name = "hide"
    key_shortcut = 'h'
    label = "Hide Tool"

    def get_cursor(self):
        if self.vis.show_all_mode: return "unhide"
        else: return "hide"
    def update_basic(self, coor):
        obj,_ = self.select_pcl(coor)
        if obj is None:
            self.confirm = self.set_show_all, True
            self.confirm_next = self.update_unhide
        else:
            self.confirm = self.vis.hide, obj

    def update_unhide(self, coor):
        def is_hidden(gi, num):
            return self.vis.gi_to_hidden[gi]
        obj,_ = self.select_pcl(coor, filter_f = is_hidden)
        if obj is None:
            self.confirm = self.set_show_all, False
        else:
            self.confirm = self.unhide, obj

    def unhide(self, obj):
        self.vis.gi_to_hidden[obj] = False
        self.set_show_all(False)

    def leave(self):
        self.set_show_all(False)
        GTool.leave(self)
    def on_reset(self):
        self.set_show_all(False)

    def set_show_all(self, value):
        if self.vis.show_all_mode != value:
            self.vis.show_all_mode = value
            self.viewport.set_cursor_by_tool()
            self.vis.refresh()

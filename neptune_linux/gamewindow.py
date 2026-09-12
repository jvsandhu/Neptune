"""Game-relative overlay tracking on X11 and KDE's XWayland path."""
from Xlib import X,display,protocol
from Xlib.ext import shape


def adapt_tracker(base,rect_type):
    class Tracker(base):
        def __init__(self,overlay_hwnd,pid=None):
            super().__init__(overlay_hwnd,pid)
            try:
                self.connection=display.Display()
                self.root=self.connection.screen().root
                self.window=self.connection.create_resource_object('window',overlay_hwnd)
            except Exception:
                self.connection=None

        def _property(self,window,name):
            return window.get_full_property(self.connection.intern_atom(name),X.AnyPropertyType)

        def make_overlay(self,click_through=True):
            if self.connection is None:return
            try:
                if click_through:self.window.shape_rectangles(shape.SO.Set,shape.SK.Input,X.Unsorted,0,0,[])
                else:self.window.shape_mask(shape.SO.Set,shape.SK.Input,0,0,X.NONE)
                self.connection.flush()
            except Exception:pass

        def attach(self):
            if self.connection is None:return False
            try:
                clients=self._property(self.root,'_NET_CLIENT_LIST')
                choices=[]
                for xid in clients.value if clients else []:
                    if xid==self.overlay_hwnd:continue
                    window=self.connection.create_resource_object('window',int(xid))
                    prop=self._property(window,'_NET_WM_NAME')
                    title=bytes(prop.value).decode('utf-8','replace') if prop else (window.get_wm_name() or '')
                    if 'forza horizon 6' not in title.lower():continue
                    if window.get_attributes().map_state!=X.IsViewable:continue
                    geometry=window.get_geometry()
                    choices.append((geometry.width*geometry.height,window))
                self.game_hwnd=max(choices,key=lambda row:row[0])[1] if choices else None
                self._active=self.game_hwnd is not None
                if self._active:self.sync()
                return self._active
            except Exception:
                self.game_hwnd=None;return False

        def sync(self):
            if not self.connection:return self.rect
            if self.game_hwnd is None and not self.attach():return self.rect
            try:
                geometry=self.game_hwnd.get_geometry()
                point=self.root.translate_coords(self.game_hwnd,0,0)
                self.rect=rect_type(point.x,point.y,geometry.width,geometry.height)
                self.restack()
            except Exception:
                self.game_hwnd=None;self.rect=rect_type()
            return self.rect

        def restack(self):
            if not self.connection or not self._active:return
            try:
                event=protocol.event.ClientMessage(window=self.window,client_type=self.connection.intern_atom('_NET_WM_STATE'),data=(32,[1,self.connection.intern_atom('_NET_WM_STATE_ABOVE'),0,1,0]))
                self.root.send_event(event,event_mask=X.SubstructureRedirectMask|X.SubstructureNotifyMask)
                self.connection.flush()
            except Exception:pass

        def game_is_foreground(self):
            if not self.connection or not self.game_hwnd:return False
            try:
                active=self._property(self.root,'_NET_ACTIVE_WINDOW')
                return bool(active is not None and len(active.value) and active.value[0] in (self.game_hwnd.id,self.overlay_hwnd))
            except Exception:return False

        def detach(self):
            super().detach()
            if self.connection:
                self.connection.close();self.connection=None
    return Tracker

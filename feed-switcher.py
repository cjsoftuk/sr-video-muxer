#!/usr/bin/env python

import sys, os
import pygtk, gtk, gobject
import pygst
pygst.require("0.10")
import gst

# VideoWidget taken from play.py in gst-python examples
class VideoWidget(gtk.DrawingArea):
    def __init__(self):
        gtk.DrawingArea.__init__(self)
        self.imagesink = None
        self.unset_flags(gtk.DOUBLE_BUFFERED)
        self.add_events (gtk.gdk.BUTTON_PRESS_MASK);

    def do_expose_event(self, event):
        if self.imagesink:
            self.imagesink.expose()
            return False
        else:
            return True

    def set_sink(self, sink):
        assert self.window.xid
        self.imagesink = sink
        self.imagesink.set_xwindow_id(self.window.xid)

class GTK_Main:
    
    def __init__(self):
        self.SOURCES = []
        self.QUEUES = []
        self.PREVIEW_WIDGETS = []
        self.SourceIndex = 0

        window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        window.set_title("Video switcher")
        window.set_default_size(960, 700)
        window.connect("destroy", gtk.main_quit, "WM destroy")
        vbox = gtk.VBox()
        window.add(vbox)

        self.entry = gtk.Entry()

        self.output_widget = VideoWidget()
        self.output_widget.set_size_request(960,540)
        
        hbox = gtk.HBox()
        vbox.pack_start(hbox)

        self.SOURCE_PREVIEW_VBOX = gtk.VBox()
        hbox.pack_start(self.SOURCE_PREVIEW_VBOX, False)

        hbox.pack_end(self.output_widget, False)

        vbox.pack_start(self.entry, False)

        self.addSrc = gtk.Button("Add source")
        vbox.add(self.addSrc)
        self.addSrc.connect("clicked", self.on_add_source)

        self.nextSrc = gtk.Button("Next source")
        vbox.add(self.nextSrc)
        self.nextSrc.connect("clicked", self.on_next_source)

        self.button = gtk.Button("Start")
        vbox.add(self.button)
        self.button.connect("clicked", self.start_stop)


        window.show_all()

        # Chain is:
        #     filesrc location=/tmp/sr_stream_1 ! decodebin2 name=dec ! queue ! ffmpegcolorspace ! autovideosink

        self.player = gst.Pipeline("player")
        self.INPUT_SWITCH = gst.element_factory_make("input-selector")

        self.DISPLAY_QUEUE = gst.element_factory_make("queue")
        colourspacer = gst.element_factory_make("ffmpegcolorspace", "converter")
        videosink = gst.element_factory_make("xvimagesink", "onair-monitor")

        videosink.TARGET_VIDEOWIDGET = self.output_widget

        self.player.add(self.INPUT_SWITCH, self.DISPLAY_QUEUE, colourspacer, videosink)
        gst.element_link_many(self.INPUT_SWITCH, self.DISPLAY_QUEUE, colourspacer, videosink)

        bus = self.player.get_bus()
        bus.enable_sync_message_emission()
        bus.add_signal_watch()
        bus.connect("sync-message::element", self.on_sync_message)
        bus.connect("message", self.on_message)

    def add_source(self, filepath, freeze = False):
        filesrc = gst.element_factory_make("filesrc")
        filesrc.set_property("location", filepath)
        self.SOURCES.append(filesrc);
        # Create a demuxer
        demux = gst.element_factory_make("decodebin2")
        # Create a queue to link to
        queue = gst.element_factory_make("queue")
        # Create a tee
        tee = gst.element_factory_make("tee")
        # Queue needs to be added first
        self.player.add(queue)
        # Are we loading a static source?
        if freeze:
            # Create a freezer
            freeze = gst.element_factory_make("imagefreeze")
            # Create a filter (slow things down!)
            caps = gst.caps_from_string("video/x-raw-rgb,framerate=25/1")
            limiter = gst.element_factory_make("capsfilter")
            limiter.set_property("caps", caps)
            # Add everything onto the player
            self.player.add(freeze, limiter)
            # Delay-link the demuxer to the freezer
            demux.connect("pad-added", self.demuxer_callback, freeze)
            # Link the freeze to the queue
            gst.element_link_many(freeze, limiter, queue)
        else:
            # Delay-link the demuxer to the queue
            demux.connect("pad-added", self.demuxer_callback, queue)
        self.QUEUES.append(queue)
        # Add the file source, demu and queue to the player chain
        self.player.add(filesrc, demux, tee)
        # Link file source to the demux
        gst.element_link_many(filesrc, demux)
        gst.element_link_many(queue, tee)
        # Link the pads
        switcher_sinkpad = self.INPUT_SWITCH.get_request_pad("sink%d" % (len(self.QUEUES) - 1))
        srcpad = tee.get_request_pad("src0")
        srcpad.link(switcher_sinkpad)
        # Select the new pad
        self.INPUT_SWITCH.set_property("active-pad", switcher_sinkpad)
        # Set up the live preview
        preview_queue = gst.element_factory_make("queue")
        colourspacer = gst.element_factory_make("ffmpegcolorspace")
        videosink = gst.element_factory_make("xvimagesink", "input%d-monitor" % (len(self.QUEUES) - 1))
        videosink.set_property("force-aspect-ratio", True)
        ## Add and link
        self.player.add(preview_queue, colourspacer, videosink)
        srcpad = tee.get_request_pad("src1")
        srcpad.link(preview_queue.get_pad("sink"))
        gst.element_link_many(preview_queue, colourspacer, videosink)
        ## Live preview display element
        preview = VideoWidget()
        preview.set_size_request(240,135)
        preview.connect("button-press-event", self.set_switcher_output, switcher_sinkpad)
        self.PREVIEW_WIDGETS.append(preview)
        # Add the preview window
        self.SOURCE_PREVIEW_VBOX.pack_start(preview, False)
        self.SOURCE_PREVIEW_VBOX.show_all()
        # Delay link the sink to the xid
        videosink.TARGET_VIDEOWIDGET = preview
        #preview.set_sink(videosink)

    def on_sync_message(self, bus, message):
        if message.structure is None:
            return
        if message.structure.get_name() == 'prepare-xwindow-id':
            # all this is needed to sync with the X server before giving the
            # x id to the sink
            print "Syncing xwindow ids"
            gtk.gdk.threads_enter()
            gtk.gdk.display_get_default().sync()
            message.src.TARGET_VIDEOWIDGET.set_sink(message.src)
            message.src.set_property("force-aspect-ratio", True)
            gtk.gdk.threads_leave()

    def on_next_source(self, w):
        self.SourceIndex += 1
        if self.SourceIndex == len(self.QUEUES):
            self.SourceIndex = 0
        sinkpad = self.INPUT_SWITCH.get_static_pad("sink%d" % self.SourceIndex)
        self.INPUT_SWITCH.set_property("active-pad", sinkpad)

    def set_switcher_output(self, w, event, sinkpad):
        print "Switching inputs to %s" % sinkpad
        self.INPUT_SWITCH.set_property("active-pad", sinkpad)

    def on_add_source(self, w):
        filepath = self.entry.get_text()
        if os.path.isfile(filepath):
            if filepath[-4:] == ".png" or filepath[-4:] == ".jpg":
                self.add_source(filepath, True)
            else:
                self.add_source(filepath)

    def start_stop(self, w):
        if self.button.get_label() == "Start":
            self.button.set_label("Stop")
            self.player.set_state(gst.STATE_PLAYING)
        else:
            self.player.set_state(gst.STATE_NULL)
            self.button.set_label("Start")
    
    def on_message(self, bus, message):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.player.set_state(gst.STATE_NULL)
            self.button.set_label("Start")
        elif t == gst.MESSAGE_ERROR:
            err, debug = message.parse_error()
            print "Error: %s" % err, debug
            self.player.set_state(gst.STATE_NULL)
            self.button.set_label("Start")
    
    def demuxer_callback(self, demuxer, pad, queue):
        print "Join sink of %s to src of %s" % (queue, demuxer)
        adec_pad = queue.get_pad("sink")
        print "sink pad has caps: %s" % adec_pad.get_caps().to_string()
        print "src pad has caps: %s" % pad.get_caps().to_string()
        pad.link(adec_pad)
        
GTK_Main()
gtk.gdk.threads_init()
gtk.main()

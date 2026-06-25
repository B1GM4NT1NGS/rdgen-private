from django import forms
from PIL import Image
from django.conf import settings
import json
import os


FALLBACK_VERSION_CHOICES = [
    ('master', 'nightly'),
    ('1.4.8', '1.4.8'),
    ('1.4.7', '1.4.7'),
    ('1.4.6', '1.4.6'),
    ('1.4.5', '1.4.5'),
    ('1.4.4', '1.4.4'),
    ('1.4.3', '1.4.3'),
    ('1.4.2', '1.4.2'),
    ('1.4.1', '1.4.1'),
    ('1.4.0', '1.4.0'),
    ('1.3.9', '1.3.9'),
    ('1.3.8', '1.3.8'),
    ('1.3.7', '1.3.7'),
    ('1.3.6', '1.3.6'),
    ('1.3.5', '1.3.5'),
    ('1.3.4', '1.3.4'),
    ('1.3.3', '1.3.3'),
    ('1.3.2', '1.3.2'),
    ('1.3.1', '1.3.1'),
    ('1.3.0', '1.3.0'),
    ('1.2.7', '1.2.7'),
    ('1.2.6', '1.2.6'),
    ('1.2.3', '1.2.3'),
    ('1.2.2', '1.2.2'),
    ('1.2.1', '1.2.1'),
    ('1.2.0', '1.2.0'),
]


def rustdesk_version_choices():
    path = getattr(settings, 'RDGEN_VERSION_FILE', '') or ''
    choices = [('master', 'nightly')]
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        for version in data.get('versions', []):
            version = str(version).strip()
            if version and version != 'master':
                choices.append((version, version))
    except Exception:
        return FALLBACK_VERSION_CHOICES
    return choices if len(choices) > 1 else FALLBACK_VERSION_CHOICES


def default_version():
    choices = rustdesk_version_choices()
    return choices[1][0] if len(choices) > 1 else '1.4.8'

class GenerateForm(forms.Form):
    sh_secret_field = forms.CharField(required=False)
    #Platform
    platform = forms.ChoiceField(choices=[('windows','Windows 64Bit'),('windows-x86','Windows 32Bit'),('linux','Linux'),('android','Android'),('macos','macOS')], initial='windows')
    version = forms.ChoiceField(choices=FALLBACK_VERSION_CHOICES, initial='1.4.8')
    help_text="'master' is the development version (nightly build) with the latest features but may be less stable"
    delayFix = forms.BooleanField(initial=True, required=False)

    #General
    exename = forms.CharField(label="Name for EXE file", required=True)
    appname = forms.CharField(label="Custom App Name", required=False)
    direction = forms.ChoiceField(widget=forms.RadioSelect, choices=[
        ('incoming', 'Incoming Only'),
        ('outgoing', 'Outgoing Only'),
        ('both', 'Bidirectional')
    ], initial='both')
    installation = forms.ChoiceField(label="Disable Installation", choices=[
        ('installationY', 'No, enable installation'),
        ('installationN', 'Yes, DISABLE installation')
    ], initial='installationY')
    settings = forms.ChoiceField(label="Disable Settings", choices=[
        ('settingsY', 'No, enable settings'),
        ('settingsN', 'Yes, DISABLE settings')
    ], initial='settingsY')
    androidappid = forms.CharField(label="Custom Android App ID (replaces 'com.carriez.flutter_hbb')", required=False)

    #Custom Server
    serverIP = forms.CharField(label="Host", required=False)
    apiServer = forms.CharField(label="API Server", required=False)
    key = forms.CharField(label="Key", required=False)
    urlLink = forms.CharField(label="Custom URL for links", required=False)
    downloadLink = forms.CharField(label="Custom URL for downloading new versions", required=False)
    compname = forms.CharField(label="Company name",required=False)

    #Visual
    iconfile = forms.FileField(label="Custom App Icon (in .png format)", required=False, widget=forms.FileInput(attrs={'accept': 'image/png'}))
    logofile = forms.FileField(label="Custom App Logo (in .png format)", required=False, widget=forms.FileInput(attrs={'accept': 'image/png'}))
    privacyfile = forms.FileField(label="Custom privacy screen (in .png format)", required=False, widget=forms.FileInput(attrs={'accept': 'image/png'}))
    iconbase64 = forms.CharField(required=False)
    logobase64 = forms.CharField(required=False)
    privacybase64 = forms.CharField(required=False)
    theme = forms.ChoiceField(choices=[
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('system', 'Follow System')
    ], initial='system')
    themeDorO = forms.ChoiceField(choices=[('default', 'Default'),('override', 'Override')], initial='default')

    #Security
    passApproveMode = forms.ChoiceField(choices=[('password','Accept sessions via password'),('click','Accept sessions via click'),('password-click','Accepts sessions via both')],initial='password-click')
    permanentPassword = forms.CharField(widget=forms.PasswordInput(), required=False)
    #runasadmin = forms.ChoiceField(choices=[('false','No'),('true','Yes')], initial='false')
    denyLan = forms.BooleanField(initial=False, required=False)
    enableDirectIP = forms.BooleanField(initial=False, required=False)
    #ipWhitelist = forms.BooleanField(initial=False, required=False)
    autoClose = forms.BooleanField(initial=False, required=False)

    #Permissions
    permissionsDorO = forms.ChoiceField(choices=[('default', 'Default'),('override', 'Override')], initial='default')
    permissionsType = forms.ChoiceField(choices=[('custom', 'Custom'),('full', 'Full Access'),('view','Screen share')], initial='custom')
    enableKeyboard =  forms.BooleanField(initial=True, required=False)
    enableClipboard = forms.BooleanField(initial=True, required=False)
    enableFileTransfer = forms.BooleanField(initial=True, required=False)
    enableAudio = forms.BooleanField(initial=True, required=False)
    enableTCP = forms.BooleanField(initial=True, required=False)
    enableRemoteRestart = forms.BooleanField(initial=True, required=False)
    enableRecording = forms.BooleanField(initial=True, required=False)
    enableBlockingInput = forms.BooleanField(initial=True, required=False)
    enableRemoteModi = forms.BooleanField(initial=False, required=False)
    hidecm = forms.BooleanField(initial=False, required=False)
    enablePrinter = forms.BooleanField(initial=True, required=False)
    enableCamera = forms.BooleanField(initial=True, required=False)
    enableTerminal = forms.BooleanField(initial=True, required=False)

    #Other
    removeWallpaper = forms.BooleanField(initial=True, required=False)

    defaultManual = forms.CharField(widget=forms.Textarea, required=False)
    overrideManual = forms.CharField(widget=forms.Textarea, required=False)

    #custom added features
    cycleMonitor = forms.BooleanField(initial=False, required=False)
    xOffline = forms.BooleanField(initial=False, required=False)
    removeNewVersionNotif = forms.BooleanField(initial=False, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        version_choices = rustdesk_version_choices()
        self.fields['version'].choices = version_choices
        self.fields['version'].initial = default_version()
        self.fields['serverIP'].initial = os.environ.get('RDGEN_DEFAULT_SERVER', '')
        self.fields['apiServer'].initial = os.environ.get('RDGEN_DEFAULT_API_SERVER', '')
        self.fields['key'].initial = os.environ.get('RDGEN_DEFAULT_KEY', '')
        self.fields['urlLink'].initial = os.environ.get('RDGEN_DEFAULT_URL_LINK', '')
        self.fields['downloadLink'].initial = os.environ.get('RDGEN_DEFAULT_DOWNLOAD_LINK', '')
        self.fields['compname'].initial = os.environ.get('RDGEN_DEFAULT_COMPANY', '')
        self.fields['appname'].initial = os.environ.get('RDGEN_DEFAULT_APP_NAME', '')
        self.fields['exename'].initial = os.environ.get('RDGEN_DEFAULT_FILE_NAME', '')

    def clean_iconfile(self):
        print("checking icon")
        image = self.cleaned_data['iconfile']
        if image:
            try:
                # Open the image using Pillow
                img = Image.open(image)

                # Check if the image is a PNG (optional, but good practice)
                if img.format != 'PNG':
                    raise forms.ValidationError("Only PNG images are allowed.")

                # Get image dimensions
                width, height = img.size

                # Check for square dimensions
                if width != height:
                    raise forms.ValidationError("Custom App Icon dimensions must be square.")
                
                return image
            except OSError:  # Handle cases where the uploaded file is not a valid image
                raise forms.ValidationError("Invalid icon file.")
            except Exception as e: # Catch any other image processing errors
                raise forms.ValidationError(f"Error processing icon: {e}")

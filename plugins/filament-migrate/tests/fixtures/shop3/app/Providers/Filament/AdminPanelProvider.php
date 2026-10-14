<?php

namespace App\Providers\Filament;

use Filament\Http\Middleware\Authenticate;
use Filament\Panel;
use Filament\PanelProvider;
use Filament\Support\Colors\Color;
use BezhanSalleh\FilamentShield\FilamentShieldPlugin;

class AdminPanelProvider extends PanelProvider
{
    public function panel(Panel $panel): Panel
    {
        return $panel
            ->default()
            ->id('admin')
            ->path('admin')
            ->login()
            ->passwordReset()
            ->brandName('Acme Admin')
            ->colors([
                'primary' => Color::Amber,
            ])
            ->navigationGroups(['Shop', 'Settings'])
            ->discoverResources(in: app_path('Filament/Resources'), for: 'App\\Filament\\Resources')
            ->plugins([
                FilamentShieldPlugin::make(),
                \Some\Vendor\FancyPlugin::make(),
            ])
            ->middleware([])
            ->authMiddleware([Authenticate::class]);
    }
}

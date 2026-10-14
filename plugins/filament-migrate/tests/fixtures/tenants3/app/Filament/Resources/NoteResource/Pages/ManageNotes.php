<?php

namespace App\Filament\Resources\NoteResource\Pages;

use App\Filament\Resources\NoteResource;
use Filament\Resources\Pages\ManageRecords;

class ManageNotes extends ManageRecords
{
    protected static string $resource = NoteResource::class;
}

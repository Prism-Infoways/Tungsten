<?php

namespace App\Filament\Resources\Posts\Schemas;

use Filament\Forms\Components\DateTimePicker;
use Filament\Forms\Components\RichEditor;
use Filament\Forms\Components\Select;
use Filament\Forms\Components\TextInput;
use Filament\Schemas\Components\Section;
use Filament\Schemas\Components\Utilities\Get;
use Filament\Schemas\Schema;

class PostForm
{
    public static function configure(Schema $schema): Schema
    {
        return $schema
            ->components([
                Section::make()
                    ->schema([
                        TextInput::make('title')->required()->rules('required|min:3|max:120'),
                        TextInput::make('slug')->required()->rules(['alpha_dash']),
                        Select::make('author_id')->relationship('author', 'name')->required(),
                        Select::make('state')
                            ->options(['draft' => 'Draft', 'published' => 'Published'])
                            ->default('draft')
                            ->live(),
                        DateTimePicker::make('published_at')
                            ->visible(fn (Get $get): bool => $get('state') === 'published'),
                        TextInput::make('rating')->numeric()->rules(['min:1', 'max:5', 'in:1,2,3,4,5']),
                        RichEditor::make('body')->required()->columnSpanFull(),
                    ])
                    ->columns(2),
            ]);
    }
}
